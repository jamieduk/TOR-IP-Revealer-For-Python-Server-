#
import argparse
import datetime
import errno
import ipaddress
import os
import re
import signal
import socket
import subprocess
import sys
import time

LOG_FILE="log.txt"
IPV4_PATTERN=re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
IPV6_PATTERN=re.compile(r"\b[0-9a-fA-F:]{2,}\b")

WELCOME_HTML="""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Welcome</title>
</head>
<body>
<h1>Welcome</h1>
<p>Connection received.</p>
</body>
</html>
"""


def normalize_ip(raw_ip):
    try:
        addr=ipaddress.ip_address(raw_ip.split("%",1)[0])
        if isinstance(addr,ipaddress.IPv6Address) and addr.ipv4_mapped:
            return str(addr.ipv4_mapped)
        return str(addr)
    except ValueError:
        return raw_ip


def load_seen_ips(log_path):
    seen=set()
    if not os.path.exists(log_path):
        return seen
    with open(log_path,"r",encoding="utf-8",errors="replace") as f:
        for line in f:
            for match in IPV4_PATTERN.findall(line):
                seen.add(normalize_ip(match))
            for match in IPV6_PATTERN.findall(line):
                if ":" in match:
                    seen.add(normalize_ip(match))
    return seen


def append_ip_log(log_path,client_ip,client_port):
    timestamp=datetime.datetime.now().isoformat(timespec="seconds")
    with open(log_path,"a",encoding="utf-8") as f:
        f.write(f"{timestamp} {client_ip}:{client_port}\n")
        f.flush()


def build_http_response(body_text,head_only=False):
    body_bytes=body_text.encode("utf-8")
    headers=(
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        f"Content-Length: {len(body_bytes)}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("utf-8")
    if head_only:
        return headers
    return headers+body_bytes


def find_pids_on_port(port):
    pids=set()
    my_pid=os.getpid()

    try:
        res=subprocess.run(
            ["ss","-tulpn",f"sport = :{port}"],
            capture_output=True,
            text=True,
            check=False,
        )
        for match in re.findall(r"pid=(\d+)",res.stdout):
            pid=int(match)
            if pid!=my_pid:
                pids.add(pid)
    except FileNotFoundError:
        pass

    if not pids:
        try:
            res=subprocess.run(
                ["fuser",f"{port}/tcp"],
                capture_output=True,
                text=True,
                check=False,
            )
            for token in res.stdout.split():
                token=token.rstrip("fucm")
                if token.isdigit():
                    pid=int(token)
                    if pid!=my_pid:
                        pids.add(pid)
        except FileNotFoundError:
            pass

    return sorted(pids)


def free_port(port):
    pids=find_pids_on_port(port)
    for pid in pids:
        try:
            print(f"Port {port} in use by PID {pid}; sending SIGTERM...",file=sys.stderr)
            os.kill(pid,signal.SIGTERM)
        except ProcessLookupError:
            continue
        except PermissionError as exc:
            print(f"Could not terminate PID {pid}: {exc}",file=sys.stderr)

    if pids:
        time.sleep(0.5)
        for pid in find_pids_on_port(port):
            try:
                print(f"PID {pid} still holding port {port}; sending SIGKILL...",file=sys.stderr)
                os.kill(pid,signal.SIGKILL)
            except ProcessLookupError:
                continue
            except PermissionError:
                pass


def bind_with_retry(host,port,retry_delay=2.0):
    use_ipv6=":" in host or host=="::"
    family=socket.AF_INET6 if use_ipv6 else socket.AF_INET

    while True:
        server=socket.socket(family,socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        if use_ipv6 and host=="::" and hasattr(socket,"IPPROTO_IPV6") and hasattr(socket,"IPV6_V6ONLY"):
            try:
                server.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,0)
            except OSError:
                pass
        try:
            server.bind((host,port))
            server.listen()
            return server
        except OSError as exc:
            server.close()
            if exc.errno==errno.EADDRINUSE:
                print(f"Port {port} already in use. Closing blocker and waiting {retry_delay}s...",file=sys.stderr)
                free_port(port)
                time.sleep(retry_delay)
            else:
                raise


def parse_args():
    parser=argparse.ArgumentParser(description="Listen on host:port, serve welcome HTML, and log incoming client IPs.")
    parser.add_argument("--host",default="::")
    parser.add_argument("--port",type=int,default=9192)
    return parser.parse_args()


def main():
    args=parse_args()
    seen_ips=load_seen_ips(LOG_FILE)
    server=bind_with_retry(args.host,args.port,retry_delay=2.0)
    print(f"Listening on [{args.host}]:{args.port} for incoming connections...",file=sys.stderr)

    try:
        while True:
            conn,addr=server.accept()
            client_ip=normalize_ip(addr[0])
            client_port=addr[1]
            with conn:
                conn.settimeout(2.0)
                request_data=b""
                try:
                    while b"\r\n\r\n" not in request_data and len(request_data)<8192:
                        chunk=conn.recv(1024)
                        if not chunk:
                            break
                        request_data+=chunk
                except socket.timeout:
                    pass

                first_line=request_data.split(b"\r\n",1)[0].decode("latin-1",errors="replace")
                head_only=first_line.upper().startswith("HEAD ")
                conn.sendall(build_http_response(WELCOME_HTML,head_only=head_only))

                if client_ip not in seen_ips:
                    seen_ips.add(client_ip)
                    append_ip_log(LOG_FILE,client_ip,client_port)
                    print(client_ip,flush=True)
                else:
                    print(f"IP already seen ({client_ip}), waiting for a new IP...",file=sys.stderr)
    finally:
        server.close()


if __name__=="__main__":
    main()
