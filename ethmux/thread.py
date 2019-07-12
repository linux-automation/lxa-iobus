import asyncio
import concurrent.futures
import threading
import queue
import json

"""This module provides an abstraction to call function running in its own thread as if they were co routines"""

callbacks = {}

def add_call(name, pass_func=None):
    if isinstance(name, str): 
        def decorator_add_call(func):
            callbacks[name] = func
            return func
        return decorator_add_call

    func = name
    name = func.__name__

    if not pass_func is None:
        name = pass_func
    callbacks[name] = func

    return func

@add_call("echo")
def echo(*args, **kwargs):
    return (args, kwargs)

def callback_router(cmd, args):
    if cmd in callbacks:
        args, kwargs = args
        return callbacks[cmd](*args, **kwargs)

    raise Exception("No route for that call: {}({})".format(cmd, args))
    return None


def cmd_reciev_worker():
    """This is the worker thread that take commands over a queue and returns the result via a future"""
    while True:
        request, future = _q.get()
        if request is None:
            break

        cmd, args = json.loads(request)

        try:
            res = callback_router(cmd, args)
            future.set_result(res)
        except Exception as e:
            future.set_exception(e)

async def send_cmd(cmd, *args):
    """Add a command to the command queue and awaits for it to finish"""
    fut = concurrent.futures.Future()
    future = asyncio.futures.wrap_future(fut)

    request = json.dumps((cmd, args))

    _q.put((request,fut))

    return await future

class Command():
    def __getattr__(self, name):
        async def tmp(*args, **dicts):
            return await send_cmd(name, args, dicts)
        return tmp

cmd = Command()

_q = queue.Queue()

_t = threading.Thread(name="sync-world", target=cmd_reciev_worker)

def start():
    print("starting thread")
    _t.start()


def stop():
    _q.put((None, 1))
    _t.join()

