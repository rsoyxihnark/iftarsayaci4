# Changelog

## [1.0.4]

- Fixed the packaged app trying to install a missing library by launching itself instead of showing an error.
- Settings and activity.log now stay beside the program instead of in the folder it was started from.
- Fixed one rejected API request blocking prayer times, the imsak calendar, and location lookups.
- Fixed prayer times and the imsak calendar never refreshing for the new day.
- An unsupported calculation method now falls back to Türkiye Diyanet instead of breaking prayer times.
- Fixed importing the program still leaving some imports undefined and raising a name error.
- Fixed prayer-time requests not sending the date, so another day's times could come back.
- Changing the calculation method now refreshes the imsak calendar.
- Fixed Temizle leaving the activity log with empty bytes and hiding new lines.
- A saved location without coordinates now stays as typed and is looked up in the background.
- Location lookups now share a cache and a one-second limit, so the tooltip, location label, and Aktif Konumu Göster stop repeating requests.
- Settings containing a percent sign no longer fail to load or save.
- Fixed the clock check calling a midnight date difference a time-zone difference.
- The Yöntem Değiştir window now opens centered on the main window and cannot hide behind it.
- Açılışta Modül Güncellemelerini Kontrol Et no longer reinstalls libraries whose version cannot be read.
- Copying text no longer writes the clipboard contents to activity.log.
- Fixed prayer-time and location responses with a BOM or a non-UTF-8 charset being garbled.
- The API rate limiter is now safe when several requests run at once.
- Fixed the location tooltip being routed through the main-thread helper twice.
- Partial lines written to the log are now buffered and logged as complete lines.
- The module loader now refuses packages that are not on its allowlist.
- Repeated prayer-time requests for the same day now use the cached result.
- Removed the unused cache code, an unreachable retry handler, other unused helpers, and leftover debug prints.
- Failed requests no longer wait after the final attempt.
- Right-click menus are created once and reused instead of on every click.
- Escape now restores the window's previous size and position when leaving full screen.
- Fixed shutdown reporting success before cleanup had finished.
- The Hakkında window now shows real library versions, or the pinned version when it cannot read one.
- The Hakkında window now lists the libraries the app uses instead of internal names.
- The certificate bundle is now looked up once instead of on every request.
- Fixed Ctrl+A in the console and command line not selecting all text.
- Açılışta Modül Güncellemelerini Kontrol Et now reads its saved value from the program's folder.
- The timezone fallback now follows the system's daylight saving changes.
- The countdown and prayer highlight now share one timer.
- Fixed the countdown percentage and duration text showing raw values.
- Logging setup now runs only once.
- The startup location choice is made once and no longer changed by the window.
- Alt-F4 no longer asks for exit confirmation twice.
- The tooltip cleanup no longer swallows unrelated errors.
- The background callback poller now slows down when there is nothing to do.

## [1.0.3]

- Fixed the app installing library versions it was not tested with.
- Fixed Açılışta Modül Güncellemelerini Kontrol Et not updating anything.
- Fixed the program failing to load as a Python module.
- Fixed the app applying settings changes that could not be saved.
- Fixed the location tooltip leaving address lookups running after the pointer left.
- Fixed the window losing its position on a screen to the left of or above the main screen.

## [1.0.2]

- The window now opens right away while prayer times, the imsak calendar, and status checks load in the background.
- Startup uses your saved coordinates, so the window no longer waits for a location lookup.
- Fixed the app not starting when settings.ini was damaged; the file is backed up and defaults are used.
- Fixed the ipinfo token appearing in activity.log.
- Fixed prayer times being requested for the wrong day around midnight and in some time zones.
- The countdown now uses the time zone reported for your location.
- Fixed the imsak calendar using the wrong place for automatic addresses.
- Fixed a second imsak calendar appearing after changing location.
- Fixed a failed location or method change leaving the prayer times out of date or cleared.
- Fixed the countdown running more than once after changing location or calculation method.
- Fixed an older automatic location result replacing a newer one.
- Fixed the location tooltip appearing after the pointer had left.
- Fixed the system clock check reporting a false drift within 30 seconds of a check.
- Fixed country flags showing the wrong country for similar names.
- Fixed Copy doing nothing after the selection was cleared.
- Fixed a failed API health check blocking the prayer times.
- Fixed the app sometimes freezing or crashing when background work updated the window.
- Fixed the app closing twice or leaving the process running after you close the window.
- The app now only installs its fixed list of required Python packages when they are missing, and no longer upgrades packages automatically.
- Fixed the developer console allowing access to internal objects beyond the values it should evaluate.
- Fixed a missing field in an imsak calendar response stopping the app from starting.

## [1.0.1]

- Hijri dates now use HijriDate, the supported library that replaces the deprecated hijri-converter.
- Fixed the imsak calendar title showing an incorrect Hijri date when no conversion was available.
- The download is now named IftarSayaci.exe, with no version number in the file name.

## [1.0.0]

- Prayer times for your location, with the calculation method you choose.
- A live countdown to iftar or sahur, with a progress bar for the day.
- The current prayer is marked green and the next prayer red.
- The imsak calendar for the current Hijri month, ready to copy.
- Automatic location lookup, with the active address shown in the window.
- A system clock check against an internet time server.
- A log panel that shows what the program is doing.
- The version number is shown in the window title and in Hakkında.
