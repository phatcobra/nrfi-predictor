$ErrorActionPreference = "Stop"

$expectedUvVersion = "uv 0.11.28"
$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uvCommand) {
    throw "uv is required. Install uv 0.11.28, then rerun this script."
}

$actualUvVersion = (uv --version).Trim()
if ($actualUvVersion -ne $expectedUvVersion) {
    throw "Expected $expectedUvVersion but found $actualUvVersion."
}

uv sync --frozen
