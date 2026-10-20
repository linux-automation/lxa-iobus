"use strict";

// A SharedWorker that centralizes EventStream handling for all tabs.
//
// Every client (tab) that wants to listen to an EventStream connects a
// MessagePort and sends a "subscribe" message containing the stream URL.
// This worker keeps at most one EventSource per URL open for the whole
// browser and forwards every message to all ports subscribed to that URL.
// When the last port for a URL goes away, the EventSource is closed.
//
// Protocol:
//   client -> worker: {type: "subscribe", url}
//   worker -> client: {type: "message", url, data}
//                     {type: "open", url}
//                     {type: "error", url}

const streams = new Map();

function create_stream(url) {
  const stream = { es: new EventSource(url), ports: new Set() };

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
    broadcast({ type: "message", url: url, data: event.data });
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

    let stream = streams.get(message.url);

    if (!stream) {
      stream = create_stream(message.url);
      streams.set(message.url, stream);
    }

    stream.ports.add(port);
  };

  // Fires when the client (tab) goes away, including on tab close.
  port.onclose = () => {
    drop_port(port);
  };

  port.start();
};
