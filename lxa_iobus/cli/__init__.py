import asyncio


def async_main(main):
    def decorated(*args, **kwargs):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        loop.run_until_complete(main(*args, **kwargs))

    return decorated
