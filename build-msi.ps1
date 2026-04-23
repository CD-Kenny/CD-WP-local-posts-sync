param(
    [string]$PythonExe = ".\.venv\Scripts\python.exe",
    [switch]$Clean,
    [switch]$SkipDependencyInstall,
    [switch]$Sign,
    [string]$SignToolPath = $env:SIGNTOOL_PATH,
    [string]$CertificateFile = $env:SIGN_CERT_FILE,
    [string]$CertificatePassword = $env:SIGN_CERT_PASSWORD,
    [string]$CertificateThumbprint = $env:SIGN_CERT_THUMBPRINT,
    [string]$CertificateSubject = $env:SIGN_CERT_SUBJECT,
    [string]$TimestampUrl = $(if ($env:SIGN_TIMESTAMP_URL) { $env:SIGN_TIMESTAMP_URL } else { "http://timestamp.digicert.com" }),
    [string]$Description = "Casual Development WordPress Post Uploader",
    [string]$DescriptionUrl = $env:SIGN_DESCRIPTION_URL,
    [switch]$NoTimestamp
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-LatestBuildExeDirectory {
    param([string]$Root)

    $directory = Get-ChildItem -Path (Join-Path $Root "build") -Directory -Filter "exe.*" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if (-not $directory) {
        throw "No build/exe.* directory was produced."
    }

    return $directory.FullName
}

function Resolve-SignToolPath {
    param([string]$RequestedPath)

    if ($RequestedPath) {
        return (Resolve-Path $RequestedPath -ErrorAction Stop).Path
    }

    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $sdkRoots = @(
        (Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"),
        (Join-Path $env:ProgramFiles "Windows Kits\10\bin")
    ) | Where-Object { $_ -and (Test-Path $_) }

    $preferred = Get-ChildItem -Path $sdkRoots -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "\\x64\\" } |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if ($preferred) {
        return $preferred.FullName
    }

    $fallback = Get-ChildItem -Path $sdkRoots -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if ($fallback) {
        return $fallback.FullName
    }

    throw "signtool.exe was not found. Install the Windows SDK or pass -SignToolPath explicitly."
}

function Get-DefaultCodeSigningCertificate {
    $stores = @(
        "Cert:\CurrentUser\My",
        "Cert:\LocalMachine\My"
    )

    $certificates = foreach ($store in $stores) {
        Get-ChildItem $store -CodeSigningCert -ErrorAction SilentlyContinue |
            Where-Object { $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date) }
    }

    return $certificates |
        Sort-Object NotAfter -Descending |
        Select-Object -First 1
}

function Get-SigningArguments {
    param([string]$TargetPath)

    $arguments = @("sign", "/fd", "SHA256")

    if (-not $NoTimestamp) {
        if (-not $TimestampUrl) {
            throw "Timestamping is enabled but no timestamp URL was provided."
        }
        $arguments += @("/td", "SHA256", "/tr", $TimestampUrl)
    }

    if ($Description) {
        $arguments += @("/d", $Description)
    }
    if ($DescriptionUrl) {
        $arguments += @("/du", $DescriptionUrl)
    }

    if ($CertificateFile) {
        $arguments += @("/f", $CertificateFile)
        if ($CertificatePassword) {
            $arguments += @("/p", $CertificatePassword)
        }
    } elseif ($CertificateThumbprint) {
        $arguments += @("/sha1", ($CertificateThumbprint -replace "\s", ""))
    } elseif ($CertificateSubject) {
        $arguments += @("/n", $CertificateSubject)
    } elseif ($Sign) {
        $defaultCertificate = Get-DefaultCodeSigningCertificate
        if (-not $defaultCertificate) {
            throw (
                "No code-signing certificate was found in the Windows certificate store. " +
                "For public distribution, obtain a real code-signing certificate and install it or export it as a PFX. " +
                "For local or internal testing, run .\setup-dev-code-signing.ps1 first, then re-run .\build-msi.ps1 -Sign."
            )
        }

        Write-Host "Using code-signing certificate from store:" $defaultCertificate.Subject
        $arguments += @("/sha1", ($defaultCertificate.Thumbprint -replace "\s", ""))
    } else {
        throw "Signing requires -CertificateFile, -CertificateThumbprint, or -CertificateSubject."
    }

    $arguments += $TargetPath
    return $arguments
}

function Sign-Artifact {
    param(
        [string]$ResolvedSignTool,
        [string]$TargetPath
    )

    Write-Host "Signing:" $TargetPath
    $signArguments = Get-SigningArguments -TargetPath $TargetPath
    & $ResolvedSignTool @signArguments
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

$resolvedPython = (Resolve-Path $PythonExe -ErrorAction Stop).Path
$signingRequested = $Sign -or $CertificateFile -or $CertificateThumbprint -or $CertificateSubject

if ($Clean) {
    Remove-Item -Path "$repoRoot\build" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path "$repoRoot\dist" -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not $SkipDependencyInstall) {
    & $resolvedPython -m pip install --upgrade pip setuptools wheel cx_Freeze
}

& $resolvedPython -m build_tools.branding
& $resolvedPython freeze_setup.py build_exe

$buildExeDir = Get-LatestBuildExeDirectory -Root $repoRoot
& $resolvedPython -m build_tools.branding --stamp-exe (Join-Path $buildExeDir "WordPressPostUploader.exe")

if ($signingRequested) {
    $resolvedSignTool = Resolve-SignToolPath -RequestedPath $SignToolPath
    $binaryFiles = Get-ChildItem -Path $buildExeDir -File -Recurse |
        Where-Object { $_.Extension -in @(".exe", ".dll", ".pyd") } |
        Sort-Object FullName

    foreach ($binary in $binaryFiles) {
        Sign-Artifact -ResolvedSignTool $resolvedSignTool -TargetPath $binary.FullName
    }
}

& $resolvedPython freeze_setup.py bdist_msi --skip-build

$msi = Get-ChildItem -Path "$repoRoot\dist" -Filter *.msi |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $msi) {
    throw "Build completed, but no MSI file was produced in $repoRoot\dist"
}

if ($signingRequested) {
    Sign-Artifact -ResolvedSignTool $resolvedSignTool -TargetPath $msi.FullName
}

Write-Host "MSI created:" $msi.FullName