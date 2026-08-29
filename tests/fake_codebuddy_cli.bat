@echo off
rem AAF-v0.5-A0 fresh-runner validation fake CodeBuddy CLI (WorkBuddy stage stub).
rem 真实 Popen 子进程会被拉起并走 stdin 协议；fake 忽略 stdin，输出合法 verdict。
echo **Result: PASS**
echo.
echo AAF_STRUCTURED_RESULT_BEGIN
echo {"verdict": "PASS", "blocking_rework": false, "blocking_provenance": "structured", "findings": [], "warnings": []}
echo AAF_STRUCTURED_RESULT_END
exit /b 0
