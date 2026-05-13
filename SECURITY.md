# Security Policy

This MCP server is designed for local use with trusted MCP clients.

## Supported Use

- Run on the same workstation or trusted server that has Abaqus installed.
- Restrict `ABAQUS_MCP_WORKSPACE` and `ABAQUS_MCP_ALLOWED_DIRS` to directories that may safely be read by the MCP client.
- Only run trusted Abaqus Python scripts.

## Not Supported

- Exposing the server directly to the public internet.
- Connecting untrusted MCP clients.
- Allowing untrusted users to write Python scripts into allowed directories.

## Reporting Issues

Please open a GitHub issue with reproduction details. Do not include private Abaqus models, `.odb` files, license files, or proprietary material data.
