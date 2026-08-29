@echo off
rem AAF FIX-002 fresh-runner fake Hermes CLI variant (ASCII only on purpose:
rem cmd.exe parses metacharacters even inside REM lines, so NO > | & % in comments).
rem - `hermes config get model` -> prints a PAID model with a fake-local base_url
rem   (https://localhost.evil.example/v1) and exits 0. The old substring matcher
rem   would classify this LOCAL_FREE; the FIX-002 hostname parser must not.
rem - `hermes chat ...`        -> write marker (real child process call evidence).
if "%1"=="config" (
  echo default: deepseek-v4-flash
  echo provider: deepseek
  echo base_url: https://localhost.evil.example/v1
  exit /b 0
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
