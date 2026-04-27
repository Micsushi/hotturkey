$action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument '"C:\Users\sushi\start-hotturkey-silent.vbs"'
Set-ScheduledTask -TaskName 'Ht start' -Action $action
