"use strict";

// Client for the EventStream SharedWorker.
//
// SharedEventSource is a drop-in replacement for EventSource whose
// connection is shared across all tabs of this origin: for every distinct
// stream URL the browser keeps only a single connection open.
//
// The optional `backlog` argument requests that the `backlog` most recent
// messages of the stream are replayed immediately after subscribing.
class SharedEventSource {
  constructor(url, backlog = 0) {
    this.url = url;
    this.onopen = null;
    this.onerror = null;
    this.onmessage = null;

    const worker = new SharedWorker("/static/event-stream-worker.js");

    this._port = worker.port;
    this._port.start();
    this._port.onmessage = (ev) => {
      const message = ev.data;

      if (message.url !== this.url) {
        return;
      }

      if (message.type === "message") {
        if (this.onmessage) {
          this.onmessage({ data: message.data });
        }
      } else if (message.type === "open") {
        if (this.onopen) {
          this.onopen(message);
        }
      } else if (message.type === "error") {
        if (this.onerror) {
          this.onerror(message);
        }
      }
    };

    this._port.postMessage({ type: "subscribe", url: url, backlog: backlog });
  }

  close() {
    this._port.close();
  }
}
