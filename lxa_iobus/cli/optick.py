#!/usr/bin/env python3

import argparse
import math
import time

from aiohttp import ClientSession

from lxa_iobus.node.remote_node import LxaRemoteNode

from . import async_main

DEFAULT_URL = "http://localhost:8080"


def mean_std(values):
    mean = sum(values) / len(values)
    std = sum((v - mean) ** 2 for v in values) ** 0.5

    return (mean, std)


async def cmd_list(args):
    url = args.url

    async with ClientSession() as session:
        response = await session.get(f"{url}/nodes/")
        nodes = await response.json()

    print("Found the following Optick devices:")
    print()

    for node in sorted(nodes["result"]):
        if not node.startswith("Optick-"):
            continue

        print(f"  - {node}")


async def cmd_calibrate(args):
    node = args.node
    input_port = args.input
    output_port = args.output
    base_url = args.base_url
    changeover_delay = args.changeover_delay
    rounds = args.rounds
    measurements_per_round = args.measurements_per_round

    input = f"ADC{input_port}"
    output = f"OUT{output_port}"

    node = await LxaRemoteNode.new(base_url, node)

    adc = node.od.adc
    outputs = node.od.outputs

    adc_when_low = list()
    adc_when_high = list()

    for _outer in range(rounds):
        await outputs.set_low(output)

        # Give the output state some time to propagate
        time.sleep(changeover_delay)

        for _inner in range(measurements_per_round):
            val = await adc.read(input)
            adc_when_low.append(val / 3.3)

        # Give the output state some time to propagate
        await outputs.set_high(output)

        time.sleep(changeover_delay)

        for _inner in range(measurements_per_round):
            val = await adc.read(input)
            adc_when_high.append(val / 3.3)

    await node.close()

    low_mean, low_std = mean_std(adc_when_low)
    high_mean, high_std = mean_std(adc_when_high)

    if low_mean > high_mean:
        low_mean, low_std, high_mean, high_std = (
            high_mean,
            high_std,
            low_mean,
            low_std,
        )

    # Set the decision boundary at the center point between the average
    # measurements for high and low values.
    mid = (low_mean + high_mean) / 2

    # Approximate the distribution of the measurements using a gaussian
    # distribution ...
    mid_low_norm = (mid - low_mean) / low_std
    mid_high_norm = (high_mean - mid) / high_std

    # ... and give a measure of how good the decision boundary is based
    # on that.
    low_correct = math.erf(mid_low_norm)
    high_correct = math.erf(mid_high_norm)

    print()
    print(f"Trigger level {mid:0.2f} provides:")
    print(f"  - {int(low_correct * 100)}% correct low estimates")
    print(f"  - {int(high_correct * 100)}% correct high estimates")
    print()

    if mid < 0.05:
        print("WARNING: The trigger level is very low.")
        print("Are all connections okay and the display set to its maximum brightness?")
        print()

    if mid > 0.95:
        print("WARNING: The trigger level is very high.")
        print("Is the sensor protected from light sources like e.g. direct sunlight?")
        print()

    if low_correct < 0.95 or high_correct < 0.95:
        print("WARNING: The trigger level has bad separation")
        print("Are all connections good, no stray light entering the setup")
        print("and automatic brightness adjustments disabled as much as possuble?")


async def cmd_latency(args):
    node = args.node
    output = args.output
    input = args.input
    base_url = args.base_url
    low_period = args.low_period
    high_period = args.high_period
    trigger_level = args.trigger_level
    iterations = args.iterations

    period = low_period + high_period

    node = await LxaRemoteNode.new(base_url, node)

    timers = node.od.timers
    triggers = node.od.triggers

    # Set the high/low decision boundary for the input pin
    await triggers.set_threshold(input, trigger_level)

    # Clear the flags register
    await timers.clear_flags()

    # Set the output low
    await timers.set_output_now(output, False)

    # Get the clock frequency of the Opticks timer in Hz
    frequency = await timers.frequency()

    # The current time on the node
    # (in clock cycles since startup as 64bit value)
    start_optick_time = await timers.time()

    # Schedule the first event one second into the future
    start_optick_time = start_optick_time + frequency

    # Calculate when to stop recording
    duration = period * iterations + 1
    duration_optick_time = int(duration * frequency)
    end_optick_time = start_optick_time + duration_optick_time

    # Calculate the periods in clock cycles
    low_period = int(low_period * frequency)
    high_period = int(high_period * frequency)

    # Generator for the output events we want to schedule.
    # Is consumed whenever there is space in the Opticks fifo.
    def gen_seq():
        ts = start_optick_time

        for _ in range(iterations):
            yield (ts, 0)
            ts += low_period
            yield (ts, 1)
            ts += high_period

    seq = iter(gen_seq())

    events = list()

    while True:
        queue_levels = await timers.queue_levels()
        queue_level_out = queue_levels[f"out{output}"]
        queue_level_in = queue_levels[f"in{input}"]

        # There are queue_level_in pending input events
        # that need to be read out.
        for _ in range(queue_level_in):
            ev = await timers.input(input)
            events.append((ev["timestamp"], "in", ev["state"]))

        # There are queue_level_out free slots in the output fifo.
        for _ in range(queue_level_out):
            try:
                ts, state = next(seq)
            except StopIteration:
                break

            await timers.set_output(output, {"timestamp": ts, "state": state})
            events.append((ts, "out", state))

        # Decide when to stop based on the Opticks perception of time
        now_optick_time = await timers.time()

        if now_optick_time > end_optick_time:
            break

        time.sleep(period)

    await node.close()

    # The input and output events are not yet correctly interleaved.
    # Change that by sorting by timestamp.
    events = sorted(events, key=lambda k: k[0])

    # Interleaved input and output events do not fit the csv data model
    # that well.
    # Instead output the state of both inputs and outputs at any specific
    # timestamp.

    print("Timestamp (ns),Output State,Input State")

    in_state = "?"
    out_state = "?"

    for ts, dir, state in events:
        if dir == "in":
            in_state = state
        else:
            out_state = state

        # Output time values in nanoseconds after measurement start
        # instead of clock cycles since Optick startup.
        ts = (ts - start_optick_time) * 1_000_000_000 // frequency

        print(f"{ts},{out_state},{in_state}")


async def cmd_capture(args):
    node = args.node
    base_url = args.base_url
    inputs = args.input
    trigger_levels = args.trigger_level

    node = await LxaRemoteNode.new(base_url, node)

    timers = node.od.timers
    triggers = node.od.triggers

    if len(trigger_levels) == 1:
        # Only one trigger level was set, broadcast it to all inputs.
        trigger_levels = trigger_levels * len(inputs)

    # Set the high/low decision boundary for the input pin
    for input, level in zip(inputs, trigger_levels):
        await triggers.set_threshold(input, level)

    # Clear the flags register
    await timers.clear_flags()

    # Get the clock frequency of the Opticks timer in Hz
    frequency = await timers.frequency()

    state = dict()

    # Get an initial state from the optick node for all inputs.
    for input in inputs:
        ev = await timers.input(input)
        state[input] = ev["state"]

    try:
        while True:
            queue_levels = await timers.queue_levels()

            events = list()

            for input in inputs:
                level = queue_levels[f"in{input}"]

                for _ in range(level):
                    ev = await timers.input(input)
                    state[input] = ev["state"]
                    events.append((ev["timestamp"], tuple(state[i] for i in inputs)))

            events = sorted(events, key=lambda ev: ev[0])

            for ts, ev_state in events:
                # Output time values in nanoseconds since optick node startup
                # instead of clock cycles.
                ts = ts * 1_000_000_000 // frequency

                line = [str(ts)] + list(str(s) for s in ev_state)

                print(", ".join(line), flush=True)

            time.sleep(0.5)
    finally:
        await node.close()


async def cmd_histogram(args):
    with open(args.csv) as fd:
        csv = fd.read()

    bin_size = args.bin_size

    bin_size_ns = int(bin_size * 1_000_000_000)

    lines = tuple(csv.strip().split("\n"))
    lines = lines[1:]
    events = tuple(ln.split(",") for ln in lines)
    events = tuple((int(ts), o, i) for ts, o, i in events)

    output_events = list()

    in_prev = "?"
    out_prev = "?"

    for event in events:
        ts, out_state, in_state = event

        if out_state != out_prev:
            output_events.append((ts, out_state, list()))
            out_prev = out_state

        if in_state != in_prev:
            if len(output_events) > 0:
                output_events[-1][2].append((ts, in_state))
            in_prev = in_state

    missed = 0
    over_capture = 0

    bins = dict()
    max_bin = 0

    for out_ts, out_edge, in_events in output_events:
        if len(in_events) == 0:
            missed += 1
            continue

        if len(in_events) > 1:
            over_capture += 1
            continue

        in_ts, in_edge = in_events[0]

        bin = (in_ts - out_ts) // bin_size_ns

        if bin > max_bin:
            max_bin = bin

        key = (bin, out_edge, in_edge)

        if key not in bins:
            bins[key] = 0

        bins[key] += 1

    print("Bin start(s),Bin end(s),rise -> rise,fall -> fall,rise -> fall,fall -> rise")

    for bin in range(max_bin + 1):
        row = list()

        row.append(bin * bin_size)
        row.append((bin + 1) * bin_size)

        for o, i in ("11", "00", "10", "01"):
            key = (bin, o, i)
            count = bins.get(key, 0)
            row.append(count)

        print(",".join(str(r) for r in row))


@async_main
async def main():
    parser = argparse.ArgumentParser(prog="optick", description="LXA Optick latency measurement utility")

    sub = parser.add_subparsers()

    sub_list = sub.add_parser("list", help="List available Optick devices")
    sub_list.add_argument(
        "url",
        type=str,
        default="http://localhost:8080",
        help="URL of a lxa-iobus server",
    )
    sub_list.set_defaults(func=cmd_list)

    sub_calibrate = sub.add_parser("calibrate", help="Calibrate the input trigger")
    sub_calibrate.add_argument("node", type=str, help="Node name of the iobus device")
    sub_calibrate.add_argument("input", type=int, help="The input to calibrate")
    sub_calibrate.add_argument("--output", type=int, help="Automatic calibration via output")
    sub_calibrate.add_argument(
        "--base_url",
        type=str,
        default=DEFAULT_URL,
        help="The time (in seconds) to leave the output low",
    )
    sub_calibrate.add_argument(
        "--changeover-delay",
        type=float,
        default=0.1,
        help="Time to wait (in seconds) between output switching and measureing",
    )
    sub_calibrate.add_argument("--rounds", type=int, default=10, help="Number of on/off cycles")
    sub_calibrate.add_argument(
        "--measurements_per_round",
        type=int,
        default=100,
        help="Number of ADC measurements per round",
    )
    sub_calibrate.set_defaults(func=cmd_calibrate)

    sub_latency = sub.add_parser("latency", help="Measure latencies")
    sub_latency.add_argument("node", type=str, help="Node name of the iobus device")
    sub_latency.add_argument("output", type=int, help="The output port to use")
    sub_latency.add_argument("input", type=int, help="The input port to use")
    sub_latency.add_argument(
        "--base_url",
        type=str,
        default=DEFAULT_URL,
        help="The time (in seconds) to leave the output low",
    )
    sub_latency.add_argument(
        "--low-period",
        type=float,
        default=0.5,
        help="The time (in seconds) to leave the output low",
    )
    sub_latency.add_argument(
        "--high-period",
        type=float,
        default=0.5,
        help="The time (in seconds) to leave the output high",
    )
    sub_latency.add_argument(
        "--trigger-level",
        type=float,
        default=0.5,
        help="The high/low decision boundary to use",
    )
    sub_latency.add_argument(
        "--iterations",
        type=int,
        default=10,
        help="The number of latencyments to take",
    )
    sub_latency.set_defaults(func=cmd_latency)

    sub_capture = sub.add_parser("capture", help="Capture timestamped events")
    sub_capture.add_argument("node", type=str, help="Node name of the iobus device")
    sub_capture.add_argument(
        "--base_url",
        type=str,
        default=DEFAULT_URL,
        help="The time (in seconds) to leave the output low",
    )
    sub_capture.add_argument(
        "--input",
        type=int,
        default=(0, 1),
        nargs="+",
        help="The inputs to capture (can be specified more than once)",
    )
    sub_capture.add_argument(
        "--trigger-level",
        type=float,
        default=(0.5, 0.5),
        nargs="+",
        help="The high/low decision boundary to use",
    )
    sub_capture.set_defaults(func=cmd_capture)

    sub_histogram = sub.add_parser("histogram", help="Analyze measurements")
    sub_histogram.add_argument("csv", type=str, help="Measurement result file")
    sub_histogram.add_argument(
        "--bin-size",
        type=float,
        default=0.001,
        help="The time interval (in seconds) to group into a bin",
    )
    sub_histogram.set_defaults(func=cmd_histogram)

    res = parser.parse_args()
    if hasattr(res, "func"):
        await res.func(res)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
