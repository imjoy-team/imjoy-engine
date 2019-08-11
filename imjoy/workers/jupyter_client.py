"""Provide worker functions for Python 3."""
import asyncio
import logging
import sys
import traceback

import janus

from .utils import format_traceback
from .python3_client import AsyncClient, task_worker, JOB_HANDLERS

from ipykernel.comm import Comm

import os

# pylint: disable=unused-argument, redefined-outer-name

logger = logging.getLogger("jupyter_client")


def display_imjoy_template(
    comm_target_name, url="https://imjoy.io/#/app", width=700, height=550
):
    iframe_html = """
    <iframe id="%(comm_target_name)s" onload="setup_imjoy_bridge()" src="%(url)s" frameborder="1" width=%(width)d height=%(height)d></iframe>
    <script type="text/Javascript">
    function setup_imjoy_bridge(){
        
        Jupyter.notebook.kernel.comm_manager.register_target('%(comm_target_name)s',
        function (comm, msg) {
            comm.on_msg((msg) => {
            var iframeEl = document.getElementById('%(comm_target_name)s')
            var data = msg.content.data

            console.log('forwarding message to iframe', data, iframeEl)

            if (["initialized",
                "importSuccess",
                "importFailure",
                "executeSuccess",
                "executeFailure"
                ].includes(data.type)) {
                iframeEl.contentWindow.postMessage(data, '*');
            } else {
                iframeEl.contentWindow.postMessage({
                type: 'message',
                data: data
                }, '*');
            }

            })

            window.comm = comm;
        });

        window.addEventListener(
        "message",
        function (e) {
            var iframeEl = document.getElementById('%(comm_target_name)s')
            if (iframeEl && e.source === iframeEl.contentWindow) {

            if (e.data.type == "message") {
                window.comm.send(e.data.data);
                console.log('forwarding message to python', e.data.data)
            }
            }
            e.stopPropagation();
        },
        false
        );
    }

    </script>
    """ % {
        "url": url,
        "width": width,
        "height": height,
        "comm_target_name": comm_target_name,
    }
    return iframe_html


class JupyterClient(AsyncClient):
    """Represent an async socketio client."""

    # pylint: disable=too-few-public-methods
    def __init__(self, conn, opt):
        """Set up client instance."""
        self.conn = conn
        self.opt = opt
        self.comm = None
        self.loop = asyncio.get_event_loop()
        self.janus_queue = janus.Queue(loop=self.loop)
        self.queue = self.janus_queue.sync_q
        self.task_worker = task_worker

    def setup(self):
        """Set up the plugin connection."""
        logger.setLevel(logging.INFO)
        if self.opt.debug:
            logger.setLevel(logging.DEBUG)
        self.comm = Comm(target_name=self.opt.id, data={})
        self.comm.on_msg(self.comm_plugin_message)

        def on_disconnect():
            if not self.opt.daemon:
                self.conn.exit(1)

        self.comm.on_close(on_disconnect)
        sys.stdout.flush()

    def connect(self):
        """Connect to the socketio server."""
        self.emit({"type": "initialized", "dedicatedThread": True})
        logger.info("Plugin %s initialized", self.opt.id)

    def emit(self, msg):
        """Emit a message to the socketio server."""
        self.comm.send(msg)

    def comm_plugin_message(self, msg):
        """Handle plugin message."""
        data = msg["content"]["data"]
        # if not self.conn.executed:
        #    self.emit({'type': 'message', 'data': {"type": "interfaceSetAsRemote"}})

        if data["type"] == "init_plugin":
            self.emit({"type": "initialized", "dedicatedThread": True})
        if data["type"] == "import":
            self.emit({"type": "importSuccess", "url": data["url"]})
        elif data["type"] == "disconnect":
            self.conn.abort.set()
            try:
                if "exit" in self.conn.interface and callable(
                    self.conn.interface["exit"]
                ):
                    self.conn.interface["exit"]()
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Error when exiting: %s", exc)
            return None
        elif data["type"] == "execute":
            if not self.conn.executed:
                self.queue.put(data)
            else:
                logger.debug("Skip execution")
                self.emit({"type": "executeSuccess"})
        elif data["type"] == "message":
            _data = data["data"]
            self.queue.put(_data)
            logger.debug("Added task to the queue")
        sys.stdout.flush()
        return None
