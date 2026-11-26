# Android emulator smoke test

`.github/workflows/android-smoke.yml` boots an API 34 (google_apis, x86_64) emulator on a GitHub-hosted
Ubuntu runner with KVM acceleration, prints the Android version and device model, and uploads a screenshot.
It runs on manual dispatch and weekly. The AVD is cached between runs to cut boot time.

## Testing your APK from a product repo
Copy the emulator step into your own workflow (same action and inputs) and replace the script:

```sh
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.example.app/.MainActivity
sleep 5
adb shell uiautomator dump /sdcard/ui.xml
adb pull /sdcard/ui.xml ui.xml
grep -q "expected text" ui.xml
adb exec-out screencap -p > after.png
```

Upload `ui.xml` and `after.png` as artifacts. Use `adb logcat -d` for crash logs.

## Publishing
Testing on the emulator needs no account. Publishing to Google Play needs a Google Play Console developer
account (one-off US$25 fee), and only at release time.
