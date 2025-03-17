with open ("manifest", "r") as file:
	x = file.readlines()

newLines = []
for line in x:
	if "<c d=" in line:
		continue
	newLines.append(line)
with open("manifest", "w") as file:
    file.writelines(newLines)