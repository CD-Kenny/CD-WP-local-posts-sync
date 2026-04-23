param(
    [string]$Subject = "CN=Casual Development Dev Code Signing",
    [string]$FriendlyName = "Casual Development Dev Code Signing",
    [int]$ValidYears = 2,
    [switch]$TrustCurrentUser,
    [string]$ExportPfxPath,
    [string]$PfxPassword
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($ValidYears -lt 1) {
    throw "-ValidYears must be at least 1."
}

if ($ExportPfxPath -and -not $PfxPassword) {
    throw "-PfxPassword is required when -ExportPfxPath is used."
}

$cert = New-SelfSignedCertificate `
    -Type CodeSigningCert `
    -Subject $Subject `
    -FriendlyName $FriendlyName `
    -CertStoreLocation "Cert:\CurrentUser\My" `
    -HashAlgorithm "SHA256" `
    -KeyAlgorithm "RSA" `
    -KeyLength 3072 `
    -KeyExportPolicy Exportable `
    -NotAfter (Get-Date).AddYears($ValidYears)

Write-Host "Created development code-signing certificate:"
Write-Host "  Subject:" $cert.Subject
Write-Host "  Thumbprint:" $cert.Thumbprint
Write-Host "  Expires:" $cert.NotAfter

if ($TrustCurrentUser) {
    $temporaryCer = Join-Path $env:TEMP ("casual-development-dev-signing-" + $cert.Thumbprint + ".cer")
    try {
        Export-Certificate -Cert $cert -FilePath $temporaryCer | Out-Null
        Import-Certificate -FilePath $temporaryCer -CertStoreLocation "Cert:\CurrentUser\Root" | Out-Null
        Import-Certificate -FilePath $temporaryCer -CertStoreLocation "Cert:\CurrentUser\TrustedPublisher" | Out-Null
        Write-Host "Trusted the certificate for the current user in Root and TrustedPublisher."
    }
    finally {
        Remove-Item $temporaryCer -Force -ErrorAction SilentlyContinue
    }
}

if ($ExportPfxPath) {
    $targetPath = (Resolve-Path (Split-Path -Parent $ExportPfxPath) -ErrorAction SilentlyContinue)
    if (-not $targetPath) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $ExportPfxPath) -Force | Out-Null
    }
    $securePassword = ConvertTo-SecureString -String $PfxPassword -AsPlainText -Force
    Export-PfxCertificate -Cert $cert -FilePath $ExportPfxPath -Password $securePassword | Out-Null
    Write-Host "Exported PFX:" $ExportPfxPath
}

Write-Host ""
Write-Host "Next step:"
Write-Host "  .\build-msi.ps1 -Sign"
Write-Host ""
Write-Host "Important: a self-signed certificate is suitable for local or internal testing only."
Write-Host "For distribution to other Windows PCs without trust warnings, use a CA-issued code-signing certificate."