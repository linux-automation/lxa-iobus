Using the REST-API
==================

The actions available through the web interface can alternatively
be performed programmatically using the :term:`REST` :term:`API` provided by the
server:

.. code-block:: bash

   # Get a list of available nodes:
   $ curl http://localhost:8080/nodes/
   {"code": 0, "error_message": "", "result": ["Ethernet-Mux-00003.00020"]}

   # Get a list of pins on a device:
   $ curl http://localhost:8080/nodes/Ethernet-Mux-00003.00020/pins/
   {"code": 0, "error_message": "", "result": ["SW", "SW_IN", "SW_EXT", "AIN0", "VIN"]}

   # Get the current status of a pin:
   $ curl http://localhost:8080/nodes/Ethernet-Mux-00003.00020/pins/SW/
   {"code": 0, "error_message": "", "result": 0}

   # Set the status of a pin:
   $ curl -d "value=0" -X POST http://localhost:8080/nodes/Ethernet-Mux-00003.00020/pins/SW/
   {"code": 0, "error_message": "", "result": null}

   # Toggle the Locator LED:
   $ curl -X POST http://localhost:8080/nodes/Ethernet-Mux-00003.00020/toggle-locator/
   {"code": 0, "error_message": "", "result": null}
