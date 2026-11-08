function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trim = $line.Trim()
        if (-not $trim -or $trim.StartsWith("#")) { continue }
        $index = $trim.IndexOf("=")
        if ($index -lt 1) { continue }
        $key = $trim.Substring(0, $index).Trim()
        $value = $trim.Substring($index + 1).Trim()
        if ($value.Length -ge 2) {
            if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        # An explicitly present empty process variable is a deliberate override.
        # GetEnvironmentVariable alone cannot distinguish it from a missing name.
        if (-not (Test-Path -LiteralPath "Env:$key")) {
            [Environment]::SetEnvironmentVariable($key, $value)
        }
    }
}
