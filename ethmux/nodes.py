import thread


def array2int(a):
    out = 0
    for i in range(len(a)):
        out |= a[i]<<(i*8)
    return out

def int2array4(c):
    out = [0,]*4
    for i in range(4):
        out[i] = 0xff & ( c>>(i*8))
    return out


class Input:
    INDEX = 0x2101
    def __init__(self, address, channel):
        self.address = address
        self.channel = channel

    async def get_pin_count(self):
        pin_count = await thread.cmd.upload(self.address, self.INDEX, (self.channel*2)+1)
        pin_count = array2int(pin_count)
        self.pins = pin_count

    async def read(self):
        tmp = await thread.cmd.upload(self.address, self.INDEX, (self.channel*2+2))
        return array2int(tmp)

    def info(self):
        return {"address": self.address, "channel": self.channel, "pins": self.pins}

class Output(Input):
    INDEX = 0x2100
    def __init__(self, address, channel):
        self.address = address
        self.channel = channel
        self.output_state = 0

    async def write(self, mask, data):

        self.output_state = (self.output_state & (~mask)) | ( data & mask)
        data = int2array4(((mask&0xffff)<<16) | (data&0xffff))
        await thread.cmd.download(self.address, self.INDEX, (self.channel*2+2), data)

    async def restore_state(self):
        await self.write(0xffff, self.output_state)

class ADC:
    def __init__(self, address, channel):
        self.address = address
        self.channel = channel

    async def read(self):
        tmp = await thread.cmd.upload(self.address, 0x2adc, (self.channel))
        return array2int(tmp)

    def info(self):
        return {"address": self.address, "channel": self.channel}



class Node:
    def __init__(self, address):
        self.address = address
        self.inputs = []
        self.outputs = []
        self.adcs = []
        self.is_alive = True

    async def get_config(self):
        protocol_count = await thread.cmd.upload(self.address, 0x2000, 0)
        protocol_count = array2int(protocol_count)
        
        protocols = []
        for i in range(protocol_count):
            tmp = await thread.cmd.upload(self.address, 0x2000, i+1)
            tmp = array2int(tmp)
            print(" *", tmp)
            protocols.append(tmp)

        # Inputs
        if 0x2101 in protocols:
            channel_count = await thread.cmd.upload(self.address, 0x2101, 0)
            channel_count = int(array2int(channel_count)/2)

            for i in range(channel_count):
                channel = Input(self.address, i)
                await channel.get_pin_count()

                self.inputs.append(channel)


        # Outpus
        if 0x2100 in protocols:
            channel_count = await thread.cmd.upload(self.address, 0x2100, 0)
            channel_count = int(array2int(channel_count)/2)

            for i in range(channel_count):
                channel = Output(self.address, i)
                await channel.get_pin_count()

                self.outputs.append(channel)

        # ADCs
        if 0x2adc in protocols:
            channel_count = await thread.cmd.upload(self.address, 0x2adc, 0)
            channel_count = int(array2int(channel_count))

            for i in range(channel_count):
                channel = ADC(self.address, i)
                self.adcs.append(channel)

    def info(self):
        inputs = []
        for ch in self.inputs:
            inputs.append(ch.info())

        outputs = []
        for ch in self.outputs:
            outputs.append(ch.info())

        adcs = []
        for ch in self.adcs:
            adcs.append(ch.info())

        return {"inputs": inputs, "outputs": outputs, "adcs": adcs, "alive": self.is_alive}


