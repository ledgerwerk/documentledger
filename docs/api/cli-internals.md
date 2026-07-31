# CLI internals

These modules are implementation reference, not a promise that every callback or helper is a stable Python integration surface.

<!-- docledger-section: api-cli-internals-modules -->

## Command and launcher modules

```{eval-rst}
.. automodule:: documentledger.cli
   :members:
   :show-inheritance:

.. automodule:: documentledger.cli_support
   :members:
   :show-inheritance:

.. automodule:: documentledger.command_catalog
   :members:
   :show-inheritance:

.. automodule:: documentledger.launcher
   :members:
   :show-inheritance:
```

The `documentledger.commands.*` modules contain registration callbacks and compatibility routing. The generated [CLI reference](../cli.md) is authoritative for command behavior.
