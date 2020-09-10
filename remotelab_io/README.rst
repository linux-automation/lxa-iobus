REST API
========

Examples
--------

::

    # get nodes
    >>> curl http://localhost:8080/nodes/
    <<< {"code": 0, "error_message": "", "result": ["IOMux-5a6ecbea", "00000000.0c0ce935.534d0000.5c12ca96"]}

    # get pins
    >>> curl http://localhost:8080/nodes/IOMux-5a6ecbea/pins/
    <<< {"code": 0, "error_message": "", "result": ["led"]}

    # get pin
    >>> curl http://localhost:8080/nodes/IOMux-5a6ecbea/pins/led/
    <<< {"code": 0, "error_message": "", "result": 0}
    
    # set pin
    >>> curl -d "value=0" -X POST http://localhost:8080/nodes/IOMux-5a6ecbea/pins/led/
    <<< {"code": 0, "error_message": "", "result": null}
