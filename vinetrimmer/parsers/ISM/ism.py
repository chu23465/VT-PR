import argparse
import requests
import xmltodict
import base64
import uuid

WV_SYSTEM_ID = [237, 239, 139, 169, 121, 214, 74, 206, 163, 200, 39, 220, 213, 29, 33, 237]

def parse_manifest_ism(manifest_url):
    r = requests.get(manifest_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                                                           'Chrome/72.0.3626.121 Safari/537.36'})

    if r.status_code != 200:
        raise Exception(r.text)
    
    # Write to file
    #with open("manifest", "w") as file:
    #    file.write(r.text)

    ism = xmltodict.parse(r.text)

    pssh = ism['SmoothStreamingMedia']['Protection']['ProtectionHeader']['#text']

    pr_pssh_dec = base64.b64decode(pssh).decode('utf16')
    pr_pssh_dec = pr_pssh_dec[pr_pssh_dec.index('<'):]
    pr_pssh_xml = xmltodict.parse(pr_pssh_dec)
    kid_hex = base64.b64decode(pr_pssh_xml['WRMHEADER']['DATA']['KID']).hex()
    
    kid = uuid.UUID(kid_hex).bytes_le

    init_data = bytearray(b'\x12\x10')
    init_data.extend(kid)
    init_data.extend(b'H\xe3\xdc\x95\x9b\x06')

    pssh = bytearray([0, 0, 0])
    pssh.append(32 + len(init_data))
    pssh[4:] = bytearray(b'pssh')
    pssh[8:] = [0, 0, 0, 0]
    pssh[13:] = WV_SYSTEM_ID
    pssh[29:] = [0, 0, 0, 0]
    pssh[31] = len(init_data)
    pssh[32:] = init_data

    print('\nPSSH (WV): ', base64.b64encode(pssh))
    print('\nKID: {}'.format(kid.hex()))

    stream_indices = ism['SmoothStreamingMedia']['StreamIndex']

    # List to store information for each stream
    stream_info_list = []

    # Iterate over each StreamIndex (as it might be a list)
    for stream_info in stream_indices if isinstance(stream_indices, list) else [stream_indices]:
        type_info = stream_info['@Type']

        if type_info in {'video', 'audio'}:
            # Handle the case where there can be multiple QualityLevel elements
            quality_levels = stream_info.get('QualityLevel', [])

            if not isinstance(quality_levels, list):
                quality_levels = [quality_levels]

            for quality_level in quality_levels:
                codec = quality_level.get('@FourCC', 'N/A')
                bitrate = quality_level.get('@Bitrate', 'N/A')
                
                # Additional attributes for video streams
                if type_info == 'video':
                    max_width = quality_level.get('@MaxWidth', 'N/A')
                    max_height = quality_level.get('@MaxHeight', 'N/A')
                    resolution = f"{max_width}x{max_height}"
                else:
                    resolution = 'N/A'
                
                # Additional attributes for audio streams
                language = stream_info.get('@Language', 'N/A')
                track_id = stream_info.get('@AudioTrackId', 'N/A') if type_info == 'audio' else None

                stream_info_list.append({
                    'type': type_info,
                    'codec': codec,
                    'bitrate': bitrate,
                    'resolution': resolution,
                    'language': language,
                    'track_id': track_id
                })

    # PSSH encoding logic in ism (Below generates WV PSSH)
    array_of_bytes = bytearray(b'\x00\x00\x002pssh\x00\x00\x00\x00')
    array_of_bytes.extend(bytes.fromhex("edef8ba979d64acea3c827dcd51d21ed"))
    array_of_bytes.extend(b'\x00\x00\x00\x12\x12\x10')
    array_of_bytes.extend(bytes.fromhex(str(kid.hex()).replace("-", "")))

    encoded_string = base64.b64encode(bytes.fromhex(array_of_bytes.hex())).decode("utf-8")

    return stream_info_list, encoded_string


def main():
    # Create an ArgumentParser object and add the 'urls' argument
    parser = argparse.ArgumentParser(description='Script for parsing Smooth Streaming manifest URLs.')
    parser.add_argument('urls',
                        help='The URLs to parse. You may need to wrap the URLs in double quotes if you have issues.',
                        nargs='+')

    # Parse the arguments
    args = parser.parse_args()

    # Iterate over the provided URLs
    for manifest_link in args.urls:
        stream_info_list, encoded_string = parse_manifest_ism(manifest_link)

        # Print information for each stream
        for stream_info in stream_info_list:
            type_info = stream_info['type']
            codec = stream_info['codec']
            bitrate = stream_info['bitrate']
            resolution = stream_info['resolution']

            if type_info == 'video':
                print(f'[INFO] VIDEO - Codec: {codec}, Resolution: {resolution}, Bitrate: {bitrate}')
            elif type_info == 'audio':
                language = stream_info['language']
                track_id = stream_info['track_id']
                print(f'[INFO] AUDIO - Codec: {codec}, Bitrate: {bitrate}, Language: {language}, Track ID: {track_id}')

        # Print PSSH information
        print('\n[INFO] PSSH:', encoded_string)

if __name__ == "__main__":
    main()