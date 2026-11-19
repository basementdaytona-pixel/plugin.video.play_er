#!/usr/bin/env bash

set -e



echo
echo "==============================================="
echo "===       XBMC PLAYER MARIA-DB CONFIG       ==="
echo

read -p "JE DATABÁZE INSTALOVANÁ LOKÁLNĚ?  ( y/n )  : " LOCAL

if [[ "$LOCAL" == "y" ]]; then
    TARGET="local"
else
    echo
    read -p "Zadej IP nebo hostname : " SSH_HOST
    read -p "Zadej SSH uživatele : " SSH_USER
    read -s -p "Zadej SSH heslo : " SSH_PASS
    echo

    TARGET="remote"
fi



# === FUNKCE PRO SPUŠTĚNÍ PŘÍKAZŮ ===

run_cmd() {
    if [[ "$TARGET" == "local" ]]; then
        bash -c "$1"
    else
        sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no ${SSH_USER}@${SSH_HOST} "$1"
    fi
}

run_sudo() {
    if [[ "$TARGET" == "local" ]]; then
        sudo bash -c "$1"
    else
        sshpass -p "$SSH_PASS" ssh -t -o StrictHostKeyChecking=no ${SSH_USER}@${SSH_HOST} "echo '$SSH_PASS' | sudo -S bash -c \"$1\""
    fi
}



# === FUNKCE PRO SAFE WRITE ===

safe_write() {
    FILE_PATH="$1"
    TMP_FILE="$2"

    EXISTS=$(run_cmd "[ -f $FILE_PATH ] && echo yes || echo no")

    if [[ "$EXISTS" == "yes" ]]; then
        SAME=$(run_cmd "cmp -s $FILE_PATH $TMP_FILE && echo same || echo diff")

        if [[ "$SAME" == "same" ]]; then
            echo "=== SOUBOR $FILE_PATH UŽ EXISTUJE A JE STEJNÝ -> SKIP ==="
            return
        else
            echo
            read -p "SOUBOR $FILE_PATH EXISTUJE A LIŠÍ SE. PŘEPSAT? (y/n): " OVERWRITE
            if [[ "$OVERWRITE" != "y" ]]; then
                echo "=== PŘESKOČENO ==="
                return
            fi
        fi
    fi

    run_sudo "cp $TMP_FILE $FILE_PATH"
    echo "=== ZAPSÁNO: $FILE_PATH ==="
}



echo
echo "===  CREATING MARIA-DB DATABASE CONFIG  ==="
echo

# === CREATE TMP FILES LOCALLY ===

TMP_MAIN=$(mktemp)
TMP_SYSTEMD=$(mktemp)



cat > "$TMP_MAIN" << 'EOF'

#################################################################################################
#
#  MYSQL XBMC  :  DATABASE OPTIMALIZATION
#  FILENAME    :  10-xbmc-player.cnf
#
#  DESCRIPTION
#    - MariaDB configuration tuned for PLAY.ER addon and Kodi 22 PIERS
#    - Adjust memory-related values according to available system RAM.
#    - Place this file in :
#      /etc/mysql/mariadb.conf.d/10-xbmc-player.cnf
#
#################################################################################################



[client]



# --- CLIENT DEFAULTS USED BY TOOLS

port = 3306
socket = /var/run/mysqld/mysqld.sock



[mysqld]



# --- BASIC BEHAVIOR

user = mysql
pid-file = /var/run/mysqld/mysqld.pid
socket = /var/run/mysqld/mysqld.sock
port = 3306
skip-name-resolve = 1



# ---INNO-DB TUNING  ( optimized for many small read/write operations used by addon cache )

innodb_buffer_pool_size = 256M
innodb_buffer_pool_instances = 1
innodb_log_file_size = 64M
innodb_log_files_in_group = 2
innodb_file_per_table = 1
innodb_flush_method = O_DIRECT
innodb_flush_log_at_trx_commit = 2
innodb_io_capacity = 200
innodb_io_capacity_max = 400



# --- CONNECTIONS / CACHE THREADS

max_connections = 50
thread_cache_size = 8
table_open_cache = 200
open_files_limit = 65535



# --- TEMPORATY TABLES / JOINTS  ( avoid excessive memory on small devices )

tmp_table_size = 32M
max_heap_table_size = 32M
join_buffer_size = 2M
sort_buffer_size = 2M
read_buffer_size = 1M
read_rnd_buffer_size = 1M



# --- PACKET SIZES

max_allowed_packet = 16M



# --- FILE FORMAT - CHARTSET

character-set-server = utf8mb4
# Prefer general collation for speed on many small-text operations; utf8mb4_general_ci
# is slightly faster than unicode_ci while being sufficiently compatible for addon usage.
collation-server = utf8mb4_general_ci



# --- DISABLE QUERY CACHE  ( deprecated, often harmful )

query_cache_type = 0
query_cache_size = 0



# --- LOGGING & SAFETY

slow_query_log = 0
log_error = /var/log/mysql/xbmc-mariadb.err



# --- Binary log disabled by default for small single-instance caches
#     Uncomment if you need replication / point-in-time recovery
#
#  server-id = 1
#  log_bin = /var/log/mysql/mysql-bin.log



# --- OTHER SAFETY LIMITS

max_connect_errors = 1000
table_definition_cache = 400



##########################################################################################
# --- Lower footprint options  ( for low-RAM devices like Raspberry Pi )
#     If you have more RAM, increase innodb_buffer_pool_size accordingly  ( 25-50% RAM )
##########################################################################################

EOF



cat > "$TMP_SYSTEMD" << 'EOF'
[Service]
Environment=MYSQLD_OPTS=
Environment=_WSREP_NEW_CLUSTER=
LimitNOFILE=65535
EOF



# === CREATE DIRS ===

run_sudo "mkdir -p /etc/mysql/mariadb.conf.d"
run_sudo "mkdir -p /etc/systemd/system/mariadb.service.d"



# === COPY TMP TO TARGET (LOCAL / REMOTE) ===

if [[ "$TARGET" == "local" ]]; then
    safe_write "/etc/mysql/mariadb.conf.d/10-xbmc-player.cnf" "$TMP_MAIN"
    safe_write "/etc/systemd/system/mariadb.service.d/xbmc-player.conf" "$TMP_SYSTEMD"
else
    sshpass -p "$SSH_PASS" scp -o StrictHostKeyChecking=no "$TMP_MAIN" ${SSH_USER}@${SSH_HOST}:/tmp/xbmc-main.cnf
    sshpass -p "$SSH_PASS" scp -o StrictHostKeyChecking=no "$TMP_SYSTEMD" ${SSH_USER}@${SSH_HOST}:/tmp/xbmc-systemd.conf

    safe_write "/etc/mysql/mariadb.conf.d/10-xbmc-player.cnf" "/tmp/xbmc-main.cnf"
    safe_write "/etc/systemd/system/mariadb.service.d/xbmc-player.conf" "/tmp/xbmc-systemd.conf"

    run_sudo "rm -f /tmp/xbmc-main.cnf /tmp/xbmc-systemd.conf"
fi



# === PERMISSIONS ( JUST IN CASE ) ===

run_sudo "chmod 644 /etc/mysql/mariadb.conf.d/10-xbmc-player.cnf"
run_sudo "chmod 644 /etc/systemd/system/mariadb.service.d/xbmc-player.conf"




echo
echo "===  RELOAD AND RESTART MARIA-DB  ==="
echo

run_sudo "systemctl daemon-reload"
run_sudo "systemctl daemon-reexec"
run_sudo "systemctl restart mariadb || systemctl restart mysql"



echo
echo "====================================="
echo "===  DATABASE TUNING COMPLETE OK  ==="
echo
