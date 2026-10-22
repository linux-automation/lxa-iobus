"use strict";

// A SharedWorker that centralizes EventStream handling for all tabs.
//
// Every client (tab) that wants to listen to an EventStream connects a
// MessagePort and sends a "subscribe" message containing the stream URL.
// This worker keeps at most one EventSource per URL open for the whole
// browser and forwards every message to all ports subscribed to that URL.
// When the last port for a URL goes away, the EventSource is closed.
//
// Every stream caches its most recent messages and replays them to new
// subscribers, so that a freshly opened tab immediately receives the
// current state instead of waiting for the next message.
//
// Protocol:
//   client -> worker: {type: "subscribe", url, backlog}
//   worker -> client: {type: "message", url, data}
//                     {type: "open", url}
//                     {type: "error", url}

const streams = new Map();

function create_stream(url, backlog) {
  const stream = {
    es: new EventSource(url),
    ports: new Set(),
    // The `backlog` most recent messages are cached so that they can be
    // replayed to new subscribers on subscribe.
    backlog: backlog,
    messages: [],
  };

  function broadcast(message) {
    for (const port of stream.ports) {
      port.postMessage(message);
    }
  }

  stream.es.onopen = (_ev) => {
    broadcast({ type: "open", url: url });
  };

  stream.es.onerror = (_ev) => {
    broadcast({ type: "error", url: url });
  };

  stream.es.onmessage = (event) => {
    const message = { type: "message", url: url, data: event.data };
    stream.messages.push(message);
    while (stream.messages.length > stream.backlog) {
      stream.messages.shift();
    }
    broadcast(message);
  };

  return stream;
}

function drop_port(port) {
  for (const [url, stream] of streams) {
    stream.ports.delete(port);

    if (stream.ports.size === 0) {
      stream.es.close();
      streams.delete(url);
    }
  }
}

self.onconnect = (event) => {
  const port = event.ports[0];

  port.onmessage = (ev) => {
    const message = ev.data;

    if (message.type !== "subscribe") {
      return;
    }

    const backlog = message.backlog || 0;

    let stream = streams.get(message.url);

    if (!stream) {
      stream = create_stream(message.url, backlog);
      streams.set(message.url, stream);
    } else if (backlog > stream.backlog) {
      // Grow the cache if a later subscriber needs a longer backlog.
      stream.backlog = backlog;
    }

    // Snapshot the cache before adding the port. The handler runs
    // atomically, so every message is either contained in the snapshot or
    // broadcast live to the new port, never both.
    const cached = stream.messages.slice(-backlog);
    stream.ports.add(port);

    for (const message of cached) {
      port.postMessage(message);
    }
  };

  // Fires when the client (tab) goes away, including on tab close.
  port.onclose = () => {
    drop_port(port);
  };

  port.start();
};
