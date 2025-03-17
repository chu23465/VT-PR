import xml.etree.ElementTree as ET
import subprocess
import argparse
import os

# Logger configuration
# logging.basicConfig(level=logging.DEBUG)

# Get the URL of the ISM manifest file as a command line argument
parser = argparse.ArgumentParser(description='Download a PlayReady protected video.')
parser.add_argument('url', metavar='URL', type=str, help='URL of the ISM manifest file')
args = parser.parse_args()

video_name = os.path.basename(args.url)
subprocess.run(['aria2c', args.url, '-o', video_name, '--out', video_name, '--allow-overwrite=true'])

# Check if the .ism file is available
manifest_file = 'manifest'
if not os.path.isfile(manifest_file):
    # Generate the .ism file with mp4split
    subprocess.run(['mp4split', video_name, '--ism'])

# Parse the manifest file with ElementTree
tree = ET.parse(manifest_file)
root = tree.getroot()

# Define function to sort resolutions by file size
def sort_resolutions(resolution):
	for child in root:
		if child.tag == 'StreamIndex':
			if child.attrib['Type'] == 'video':
				for fragment in child:
					if (fragment.get('MaxWidth', '0') + 'x' + fragment.get('MaxHeight', '0')) == resolution:
						return int(fragment.get('Size', 0))
	return 0

# Show the available resolutions for the video sorted by file size
video_resolutions = []
for child in root:
	if child.tag == 'StreamIndex':
		if child.attrib['Type'] == 'video':
			for fragment in child:
				resolution = fragment.get('MaxWidth', '0') + 'x' + fragment.get('MaxHeight', '0')
				if resolution not in video_resolutions and resolution != '0x0':
					video_resolutions.append(resolution)

format_resolutions = []
for i, resolution in enumerate(sorted(video_resolutions, key=sort_resolutions, reverse=True)):
	is_hdr = False
	codec = ''
	bitrate = ''
	for child in root:
		if child.tag == 'StreamIndex':
			if child.attrib['Type'] == 'video':
				for fragment in child:
					if (fragment.get('MaxWidth', '0') + 'x' + fragment.get('MaxHeight', '0')) == resolution:
						codec = fragment.get('FourCC', '')
						bitrate = fragment.get('Bitrate', '')
						if codec in ['hev1']:
							es_hdr = True
	resolution_string = str(i+1) + '. ' + resolution
	if is_hdr:
		resolution_string += ' - HDR: true'
	else:
		resolution_string += ' - HDR: false'
	if codec != '':
		resolution_string += ' - Codec: ' + codec
	if bitrate != '':
		resolution_string += ' - Bitrate: ' + bitrate + ' kbps'
	format_resolutions.append(resolution_string)

print('Available resolutions for the video:')
for resolution in format_resolutions:
	print(resolution)

# Get information about audio channels
audio_channels = []
for child in root:
	if child.tag == 'StreamIndex':
		if child.attrib['Type'] == 'audio':
			lang_list = []
			for fragment in child:
				codec = fragment.get('FourCC', '')
				bitrate = fragment.get('Bitrate', '')
				lang = fragment.get('Language', '')
				if codec not in audio_channels and bitrate != '':
					audio_channels.append(codec)
					bitrate_kbps = int(bitrate) // 1000
					for l in lang.split(','):
						lang_list.append(l.strip())
					audio_channel_string = str(len(audio_channels)) + '. Codec: ' + codec + ' - Bitrate: ' + str(bitrate_kbps) + ' kbps'
					print(audio_channel_string)

# Delete the .ism file
os.remove(manifest_file)