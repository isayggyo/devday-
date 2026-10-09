$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$lectureFixtureDirectory = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../e2e/fixtures')).Path
$lectureAudioPath = Join-Path $lectureFixtureDirectory 'lecture.wav'
$lectureTextPath = Join-Path $lectureFixtureDirectory 'lecture.txt'
$lectureSynthesizer = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $lectureVoices = $lectureSynthesizer.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'en-US' }
    if (-not $lectureVoices) { throw 'An installed en-US Windows speech voice is required to regenerate the fixture.' }
    $lectureVoice = @($lectureVoices)[0].VoiceInfo.Name
    $lectureSynthesizer.SelectVoice($lectureVoice)
    $lectureSynthesizer.Rate = 0
    $lectureSynthesizer.Volume = 100
    $lectureAudioFormat = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    $lectureSynthesizer.SetOutputToWaveFile($lectureAudioPath, $lectureAudioFormat)
    $lectureSynthesizer.Speak([System.IO.File]::ReadAllText($lectureTextPath, [System.Text.Encoding]::UTF8))
    $lectureSynthesizer.SetOutputToNull()
    Write-Output "Created spoken lecture fixture using $lectureVoice at $lectureAudioPath"
} finally {
    $lectureSynthesizer.Dispose()
}
