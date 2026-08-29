@echo off
rem AAF-v0.5-A0 fresh-runner validation fake Hermes CLI (ASCII only on purpose:
rem cmd.exe parses metacharacters even inside REM lines, so NO > | & % in comments).
rem - `hermes config get model` -> exit 1 (config probe failure -> COST_UNKNOWN path)
rem - `hermes chat ...`        -> write marker (real child process call evidence).
rem argv-level evidence (-m/--provider passthrough) is covered by unit tests.
if "%1"=="config" (
  exit /b 1
)
if defined FAKE_HERMES_MARKER (
  echo SPAWNED > "%FAKE_HERMES_MARKER%"
)
echo FAKE HERMES EXECUTOR: fresh-runner validation stub (no real inference)
echo.
echo AAF_STRUCTURED_RESULT_BEGIN
echo {"status": "SUCCESS", "commit": null, "changed_files": [], "warnings": []}
echo AAF_STRUCTURED_RESULT_END
exit /b 0
