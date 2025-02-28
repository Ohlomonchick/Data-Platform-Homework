#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import paramiko
import time

TEAM_HOST = "176.109.91.34"     # Адрес jump-сервера
TEAM_USER = "team"             # Имя пользователя для SSH на jump-сервер
TEAM_PASSWORD = os.environ.get("TEAM_PASSWORD")  # Пароль для jump-сервера (используется при sudo)
HADOOP_PASSWORD = os.environ.get("HADOOP_PASSWORD")   # Пароль для пользователя hadoop
PRIVATE_KEY_PATH = "C:/Users/Dmitry/.ssh/id_rsa"

# Путь к локальным файлам, которые нужно отправить на jump
LOCAL_NGINX_DEF = "nginx-def.conf"
LOCAL_NGINX_YA = "nginx-ya.conf"
LOCAL_NGINX_DH = "nginx-dh.conf"
LOCAL_YARN_SITE = "yarn-site.xml"
LOCAL_MAPRED_SITE = "mapred-site.xml"

# Папка на jump-сервере, куда мы временно складываем конфиги
REMOTE_TMP_DIR = f"/tmp_configs"

# Список адресов нод (имена/алиасы должны резолвиться на jump-сервере. Замените на те, что указаны у вас)
NODES = {
    "tmpl-nn": "tmpl-nn",
    "tmpl-dn-00": "tmpl-dn-00",
    "tmpl-dn-01": "tmpl-dn-01"
}


def run_command(ssh_client, command, use_sudo=False, print_output=True):
    """
    Executes a command on a remote SSH client with exec_command.
    If `use_sudo` is True, it will prepend `echo <TEAM_PASSWORD> | sudo -S`.
    """
    if use_sudo:
        command = f"echo '{TEAM_PASSWORD}' | sudo -S -p '' {command}"

    stdin, stdout, stderr = ssh_client.exec_command(command)
    exit_code = stdout.channel.recv_exit_status()

    out = stdout.read().decode("utf-8", errors="ignore")
    err = stderr.read().decode("utf-8", errors="ignore")

    if print_output:
        print(f"COMMAND: {command}")
        print(f"EXIT CODE: {exit_code}")
        if out:
            print("--- STDOUT ---")
            print(out)
        if err:
            print("--- STDERR ---")
            print(err)

    return exit_code, out, err


def open_interactive_shell(ssh_client):
    """
    Opens an interactive shell channel on the existing Paramiko SSHClient session.
    Returns the channel object (invoke_shell).
    """
    shell = ssh_client.invoke_shell()
    time.sleep(1)  # Give the shell a moment to initialize
    # Drain any initial welcome message or prompts
    if shell.recv_ready():
        shell.recv(9999)
    return shell


def run_shell_command_in_shell(shell, cmd, wait=1.0):
    """
    Sends a command to an existing shell and waits 'wait' seconds,
    then reads and returns whatever is in the buffer.
    """
    cmd_with_exit = f'{cmd}; echo "EXITCODE:$?"'
    shell.send(cmd_with_exit + "\n")
    time.sleep(wait)
    output = ""
    while shell.recv_ready():
        output_part = shell.recv(9999).decode("utf-8", errors="ignore")
        output += output_part
    # For debugging, you can uncomment:
    # print(f"[SHELL CMD]: {cmd}")
    # print(f"[SHELL OUTPUT]: {output}")
    return output


def main():
    # 1. Подключаемся к jump-серверу
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    private_key = paramiko.RSAKey(filename=PRIVATE_KEY_PATH)

    print(f"[*] Connecting to jump server {TEAM_HOST} as {TEAM_USER}...")
    ssh.connect(TEAM_HOST, username=TEAM_USER, pkey=private_key)
    print("[+] Connected.")

    # 2. Создаём на jump-сервере временную директорию, если её нет
    run_command(ssh, f"mkdir -p {REMOTE_TMP_DIR}", use_sudo=True)
    run_command(ssh, f"chmod 777 -R {REMOTE_TMP_DIR}", use_sudo=True)

    # 3. Передаём необходимые файлы через SFTP
    sftp = ssh.open_sftp()
    sftp.put(LOCAL_NGINX_DEF, REMOTE_TMP_DIR + "/nginx-def.conf")
    sftp.put(LOCAL_NGINX_YA,  REMOTE_TMP_DIR + "/nginx-ya.conf")
    sftp.put(LOCAL_NGINX_DH,  REMOTE_TMP_DIR + "/nginx-dh.conf")
    sftp.put(LOCAL_YARN_SITE, REMOTE_TMP_DIR + "/yarn-site.xml")
    sftp.put(LOCAL_MAPRED_SITE, REMOTE_TMP_DIR + "/mapred-site.xml")
    sftp.close()

    # 4. Настраиваем Nginx на jump (примерно как в инструкции)
    run_command(ssh, f"cp {REMOTE_TMP_DIR}/nginx-def.conf /etc/nginx/sites-available/default", use_sudo=True)
    run_command(ssh, "systemctl restart nginx", use_sudo=True)

    # 5. Скачиваем csv на jump
    run_command(ssh,
        f"wget --no-check-certificate -O /home/{TEAM_USER}/data.csv "
        "https://rospatent.gov.ru/opendata/7730176088-tz/data-20241101-structure-20180828.csv"
    )

    # === NOW use interactive shell for HDFS steps ===
    shell = open_interactive_shell(ssh)

    # A) Become hadoop user on the jump node:
    run_shell_command_in_shell(shell, f"echo '{TEAM_PASSWORD}' | sudo -S -p '' -i -u hadoop", wait=2.0)

    # B) Now SSH into tmpl-nn as 'hadoop':
    run_shell_command_in_shell(shell, f"ssh -o StrictHostKeyChecking=no {NODES['tmpl-nn']}", wait=2.0)

    # Create a directory /test
    run_shell_command_in_shell(shell, "hdfs dfs -mkdir /test", wait=2.0)
    # Put file in /test
    run_shell_command_in_shell(shell, f"hdfs dfs -put /home/hadoop/data.csv /test", wait=2.0)

    # Done with HDFS commands, exit from tmpl-nn shell:
    run_shell_command_in_shell(shell, "exit", wait=1.0)


    # 6. Копируем yarn-site.xml и mapred-site.xml на все ноды через jump
    for node_alias in NODES.values():
        run_shell_command_in_shell(
            shell,
            f"scp -o StrictHostKeyChecking=no {REMOTE_TMP_DIR}/yarn-site.xml {node_alias}:/home/hadoop/hadoop-3.4.0/etc/hadoop"
        )
        run_shell_command_in_shell(
            shell,
            f"scp -o StrictHostKeyChecking=no {REMOTE_TMP_DIR}/mapred-site.xml {node_alias}:/home/hadoop/hadoop-3.4.0/etc/hadoop"
        )

    # 7. Заходим на tmpl-nn, запускаем start-yarn.sh (non-interactively)
    run_shell_command_in_shell(shell, f"ssh -o StrictHostKeyChecking=no {NODES['tmpl-nn']}", wait=2.0)
    run_shell_command_in_shell(shell, "/home/hadoop/hadoop-3.4.0/sbin/start-yarn.sh", wait=2.0)
    run_shell_command_in_shell(shell, "exit", wait=1.0)

    # 8. Доп. настройка Nginx (копирование конфигов nginx-ya.conf, nginx-dh.conf)
    run_command(ssh, f"cp /etc/nginx/sites-available/default /etc/nginx/sites-available/nn", use_sudo=True)
    run_command(ssh, f"cp {REMOTE_TMP_DIR}/nginx-ya.conf /etc/nginx/sites-available/ya", use_sudo=True)
    run_command(ssh, f"cp {REMOTE_TMP_DIR}/nginx-dh.conf /etc/nginx/sites-available/dh", use_sudo=True)

    # Активируем конфигурации
    run_command(ssh, "ln -sf /etc/nginx/sites-available/ya /etc/nginx/sites-enabled/ya", use_sudo=True)
    run_command(ssh, "ln -sf /etc/nginx/sites-available/dh /etc/nginx/sites-enabled/dh", use_sudo=True)
    run_command(ssh, "ln -sf /etc/nginx/sites-available/nn /etc/nginx/sites-enabled/nn", use_sudo=True)

    # Перезапускаем Nginx
    run_command(ssh, "systemctl restart nginx", use_sudo=True)

    # 9. Информация по пробросу портов
    print("[*] Для просмотра веб-интерфейсов (ResourceManager, HistoryServer) сделайте локально:")
    print(f"    ssh -L 9870:127.0.0.1:9870 -L 8088:127.0.0.1:8088 -L 19888:127.0.0.1:19888 {TEAM_USER}@{TEAM_HOST}")

    # Закрываем сессию
    shell.close()
    ssh.close()
    print("[+] Скрипт завершил работу.")


if __name__ == "__main__":
    main()
