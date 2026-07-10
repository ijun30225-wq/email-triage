on run
	set basePath to (POSIX path of (path to home folder)) & "email-triage/"
	set payloadPath to basePath & ".notify_payload"
	set urlPath to basePath & ".last_url"
	set payloadText to ""
	try
		set payloadText to do shell script "cat " & quoted form of payloadPath & " 2>/dev/null"
	end try
	if payloadText is not "" then
		-- launched by triage.py: post the notification, remember its URL
		-- paragraphs handles any line-ending style
		set theParts to paragraphs of payloadText
		set theTitle to item 1 of theParts
		set theSub to item 2 of theParts
		set theBody to item 3 of theParts
		set theURL to item 4 of theParts
		do shell script "printf %s " & quoted form of theURL & " > " & quoted form of urlPath
		do shell script "rm -f " & quoted form of payloadPath
		display notification theBody with title theTitle subtitle theSub sound name "Glass"
	else
		-- launched by the user clicking a notification: open the email
		try
			set theURL to do shell script "cat " & quoted form of urlPath & " 2>/dev/null"
			if theURL is not "" then open location theURL
		end try
	end if
end run
