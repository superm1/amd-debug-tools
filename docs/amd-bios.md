# BIOS log parser
`amd-bios` is a a tool that can be used to enable or disable BIOS AML debug logging
-and to parse a kernel log that contains BIOS logs.

## `amd-bios trace`
Modify BIOS AML trace debug logging.

One of the following arguments must be set for this command:

        --enable       Enable BIOS AML tracing
        --disable      Disable BIOS AML tracing

The following optional arguments are supported for this command:

        --tool-debug   Enable tool debug logging

## `amd-bios parse`
Parses a kernel log that contains BIOS AML debug logging and produces a report.

The following optional arguments are supported for this command:

        --input INPUT  Optional input file to parse
        --tool-debug   Enable tool debug logging

## `amd-bios --version`
This will print the version of the tool and exit.
