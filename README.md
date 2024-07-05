Multi-threaded, multi-tabbed, ephemeral-connection based graphical SFTP cilent written in Python and Qt5


basic instructions:
type in a site ip/hostname, username, password, and optionally port in the text boxes at the top
hitting enter in the password field or port field should start a connection
in theory if you are connected to one site and do this again it will open another tab to the new additional site
right-click should give you a menu to upload/download items (if local window, upload, if remote window, download)
double clicking a remote item should either try to cd into it if its a directory or download it and prompt you for a filename/location
