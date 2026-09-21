param(
    [string]$KeyPath = (Join-Path $HOME ".macro_pit\deepseek_api_key.txt")
)

$secureKey = Read-Host "Paste the DeepSeek API key (input is hidden)" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    if ([string]::IsNullOrWhiteSpace($plainKey) -or $plainKey.Length -lt 10) {
        throw "The API key is empty or unexpectedly short."
    }
    $directory = Split-Path -Parent $KeyPath
    [IO.Directory]::CreateDirectory($directory) | Out-Null
    $utf8NoBom = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($KeyPath, $plainKey.Trim(), $utf8NoBom)

    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls.exe $KeyPath /inheritance:r /grant:r "$($currentUser):(R,W)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "The key was written, but restricting its ACL failed."
    }
    Write-Host "DeepSeek credential saved for scheduled tasks: $KeyPath"
}
finally {
    if ($bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    $plainKey = $null
    $secureKey = $null
}
