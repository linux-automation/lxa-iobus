import asyncio
import socket
import json

import logging

logger = logging.getLogger("controller")


class UnixMassageServer:

    SYSTEMD_SOCKET = 3
    def __init__(self, handler, path, loop):
        self.path = path
        self.loop = loop
        self.handler = handler

        self.is_shutdown = asyncio.Future()
        logger.info("Setup unix socket %s", path)

        try:
            #TODO: add code to get the socket from a systemd file descriptor
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            self.sock.setblocking(False)
            self.sock.bind(self.path)
            self.sock.listen(0)
        except OSError as e:
            if e.errno == 98:
                print("{} is already used otherwithe".format(self.path))
            raise e

        asyncio.ensure_future(self.unix_server())

    async def handle_unix_connection(self, conn):
        logger.info("New unix connection")
        try:
            while True:
                requ = await self.loop.sock_recv(conn, 4096)
                if len(requ) == 0:
                    break
                respons = await self.handler(requ)
                await self.loop.sock_sendall(conn, respons.encode())
        except BrokenPipeError:
            pass

        logger.info("Unix connection closed")
        conn.close()

    async def unix_server(self):
        while True:
            accept_aws = self.loop.sock_accept(self.sock)
            done, pending = await asyncio.wait((accept_aws, self.is_shutdown), return_when=asyncio.FIRST_COMPLETED)
            if accept_aws in done:
                conn, addr = await accept_aws
                asyncio.ensure_future(self.handle_unix_connection(conn))

            if self.is_shutdown in done:
                logger.info("Shutdown unix socket")
                if await self.is_shutdown:
                    break
        self.sock.close()
        self.loop.stop()

    def shutdown(self):
        self.is_shutdown.set_result(True)

api_mapping = {}

def error(msg):
    return json.dumps({"error": True, "error_msg": msg})

async def handel_unix(request):
    
    try:
        request = request.decode()
        request = json.loads(request)
        cmd = request["cmd"]
        args = request["args"]

        call = api_mapping.get(cmd, None)
        if call is None:
            return error("No such command: {}".format(call))

        args, kwargs = args

        response = await call(*args, **kwargs)

        response = json.dumps({"error": False, "error_msg": "", "resulte": response})
        return response
    except BaseException as e:
        return error(str(e))
            



def startup_socket(unix_socket_path, loop):
    return UnixMassageServer(handel_unix, unix_socket_path, loop)
