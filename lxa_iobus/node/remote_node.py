import logging

from aiohttp import ClientResponseError, ClientSession

from lxa_iobus.canopen import SdoAbort

from .base_node import LxaBaseNode

logger = logging.getLogger("lxa_iobus.remote_node")


class LxaRemoteNode(LxaBaseNode):
    @classmethod
    async def new(cls, base_url, node_name):
        """Set up a new LxaRemoteNode

        The node setup requires some communication with the IOBus server
        and the node, which happens in an `async` fashion.
        This async classmethod performs this setup and returns the new
        LxaRemoteNode.

        The remote node can be controlled via the ObjectDirectory instance
        stored in the `node.od` attribute.

        Arguments:

            - `base_url`: The URL the remote lxa iobus server is available at,
              e.g. `"http://localhost:8080"` for a server running on localhost.
            - `node_name`: The name of the node according to the remote IOBus
              server.

        Returns: An LxaRemoteNode instance that can be used just like an
        LxaBusNode.
        """

        session = ClientSession(raise_for_status=True)

        response = await session.get(f"{base_url}/nodes/{node_name}/")
        body = await response.json()
        address = body["result"]["info"]["address"]
        lss_address = list(int(a) for a in address.split("."))

        this = cls(session, base_url, node_name, lss_address)

        await this.setup_object_directory()

        return this

    def __repr__(self):
        return f"<LxaRemoteNode(address={self.address}, base_url={self.base_url})>"

    def __init__(self, session, base_url, node_name, lss_address):
        """Do not use directly.

        Use await LxaRemoteNode.new() instead."""

        super().__init__(lss_address)

        self.session = session
        self.base_url = base_url
        self.node_name = node_name

    def _sdo_url(self, index, sub_index):
        return f"{self.base_url}/api/v2/node/{self.node_name}/raw_sdo/0x{index:04x}/{sub_index}"

    async def sdo_read(self, index, sub_index, _timeout=None):
        """Perform a raw SDO read on the node

        This returns the content of the SDO as raw bytes.
        In most cases you should use the ObjectDirectory instance at `node.od`
        instead to read and decode the SDO content.
        """

        try:
            response = await self.session.get(self._sdo_url(index, sub_index))
            return await response.read()
        except ClientResponseError as e:
            logger.warn(f"sdo_read() failed for node {self.name}: {e}")

            # We do not have all the information we need for a proper SdoAbort,
            # but no node id and error id "General error" should be good enough.
            raise SdoAbort(0, index, sub_index, 0x08000000) from e

    async def sdo_write(self, index, sub_index, data, _timeout=None):
        """Perform a raw SDO write on the node

        This sets the content of the SDO from raw bytes.
        In most cases you should use the ObjectDirectory instance at `node.od`
        instead to encode and set the SDO content.
        """

        try:
            await self.session.post(self._sdo_url(index, sub_index), data=data)
        except ClientResponseError as e:
            logger.warn(f"sdo_write() failed for node {self.name}: {e}")

            # We do not have all the information we need for a proper SdoAbort,
            # but no node id and error id "General error" should be good enough.
            raise SdoAbort(0, index, sub_index, 0x08000000) from e

    async def close(self):
        """Clean up the session

        You should call close before dropping the reference to this remote node
        to cleanly tear down the connection to the HTTP server.
        """

        await self.session.close()
