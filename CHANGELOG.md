# Changelog

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
