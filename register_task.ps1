# 注册 Windows 计划任务：每 5 分钟跑一轮采集（比常驻脚本更抗崩溃）
# 右击「用 PowerShell 运行」，若提示权限不足请以管理员运行。
$ErrorActionPreference = 'Stop'
$dir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$py   = (Get-Command python).Source
$name = 'BiliMechabellumLiveRecorder'

$action = New-ScheduledTaskAction -Execute $py `
    -Argument ('"{0}\monitor.py" collect --once' -f $dir) `
    -WorkingDirectory $dir

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 4) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Settings $settings -Description '每5分钟采集B站钢铁指挥官直播场次' -Force

Write-Host "已注册计划任务: $name"
Write-Host "查看: Get-ScheduledTask -TaskName $name"
Write-Host "停止: Unregister-ScheduledTask -TaskName $name -Confirm:`$false"
