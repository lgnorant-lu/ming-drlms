<#
.SYNOPSIS
PowerShell wrapper to run the DRLMS TUI with protobuf compatibility workaround.

.DESCRIPTION
This script sets the PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION environment variable
to 'python' before launching the TUI. This avoids the "Descriptors cannot be 
created directly" runtime error when generated _pb2.py files were created with 
an older protoc version than the installed Python protobuf package supports.

Temporary workaround (slower): use pure-Python protobuf implementation
Permanent fix options:
  1. Regenerate protos with protoc >= 3.19.0
  2. Downgrade protobuf package to 3.20.x

.EXAMPLE
.\scripts\run_tui.ps1

.NOTES
Author: DRLMS Team
Date: 2025-01-21
#>

# Set environment variable for current process only
$env:PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION = 'python'

Write-Host "[TUI] Using pure-Python protobuf implementation (compatibility mode)" -ForegroundColor Yellow
Write-Host "[TUI] Starting DRLMS TUI..." -ForegroundColor Green

# Run the CLI command
& ming-drlms tui
