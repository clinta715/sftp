#!/bin/bash

smtp_host="172.16.1.25"
smtp_destination="DL_ITMonitor@dairylandlabs.com"
smtp_from="backups@dairylandlabs.com"
base_directory="/mnt/backup/"

figlet -f slant resyncz.sh

# Check if folder argument is provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <folder>"
    exit 1
fi

# Check if folder exists
if [ ! -d "$1" ]; then
    echo "Error: Folder '$1' does not exist."
    exit 1
fi

#!/bin/bash

# Generate a random string
random_string=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 10)

# Combine the random string with the word 'remote'
error_log="/tmp/resyncz_${random_string}.log"

# Display the generated filename
echo "Generated filename: $error_log"

# Generate a unique folder name using date/time and a random string
timestamp=$(date +"%Y%m%d%H%M%S")
random_string=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 8 | head -n 1)
random_folder_name="${timestamp}_${random_string}"

# Combine the base directory and random folder name
random_folder_path="${base_directory}${random_folder_name}"

# Create the folder if it doesn't exist
# mkdir -p "$random_folder_path"

# Now you can use $random_folder_path in your code
tmp_folder="$random_folder_path"

echo "Generated random folder: $tmp_folder"
echo "Base directory for mounts: $base_directory"

# Create a temporary folder for mounting
#tmp_folder="/mnt/backup/tmpz"
echo "Create temporary folder: $tmp_folder"
mkdir -p "$tmp_folder"

# Get the directory where the script was executed
current_directory=$(dirname "$0")
smtp_file="$current_directory/smtp.txt"

# Check if smtp.txt file exists
if [ -e "$smtp_file" ]; then
    # Read lines from smtp.txt and assign them to variables
    {
        IFS= read -r smtp_host
        IFS= read -r smtp_from
        IFS= read -r smtp_destination
        IFS= read -r base_directory
    } < "$smtp_file"

    echo "SMTP Host: $smtp_host"
    echo "SMTP From: $smtp_from"
    echo "SMTP Destination: $smtp_destination"
    echo "Base Directory: $base_directory"
else
    echo "Error: smtp.txt file not found in the current directory."
fi

# Iterate through .sync files
for file in "$1"/*.syncz; do
    if [ -f "$file" ]; then
        source_info=$(sed -n '1p' "$file")
        dest_archive=$(sed -n '2p' "$file")

        # Extract source host and path
        source_host=$(echo "$source_info" | awk -F ':' '{print $1}')
        source_path=$(echo "$source_info" | awk -F ':' '{print $2}')

        # Check if source host and path are valid
        if [ -n "$source_host" ] && [ -n "$source_path" ]; then
            # Mount the remote source path
            echo "Mount the remote $source_path on $source_host to $tmp_folder"
            sshfs "root@$source_host:$source_path" "$tmp_folder"

            # Check if mount was successful
            if [ $? -eq 0 ]; then
                echo "Creating archive $dest_archive"

                # Generate a random string for the lock file name
                base_filename=$(basename "$dest_archive")
                lock_file="/tmp/${base_filename}.lock"

                echo "Lock file path: $lock_file"

                if [ -e "$lock_file" ]; then
                    echo "File $lock_file exists. Returning from function." | tee -a "$error_log"
                    return 1
                fi

                if [ -e "$dest_archive" ]; then
                  echo "Removing old $dest_archive"
                  rm "$dest_archive"
                fi

                # Write the current process number to the lock file
                echo $$ > "$lock_file"

                tar -caf "$dest_archive" -C "$tmp_folder" --zstd .

                # Unmount the remote source path
                echo "Unmount: $tmp_folder"
                fusermount -u "$tmp_folder"

                echo "Removing $lock_file"
                rm "$lock_file"
            else
                echo "Error: Unable to mount source path from $source_host" | tee -a "$error_log"
            fi
        else
            echo "Error: Invalid source host or source path in $file" | tee -a "$error_log"
        fi
    fi
done

if [ -e "$error_log" ]; then
    python sendEmail.py -o -s "$smtp_host" -m "resyncz.sh ERRORS DURING SYNC" -f "$smtp_from" -t "$smtp_destination" -a "$error_log" -p 25 -b "resyncz.sh ERRORS DURING SYNC"
    echo "Remove $error_log"
    rm "$error_log"
else
    python sendEmail.py -o -s "$smtp_host" -m "resyncz.sh SUCCESS NO ERRORS" -f "$smtp_from" -t "$smtp_destination" -p 25 -b "resyncz.sh SUCCESS NO ERRORS"
fi

# Clean up temporary folder
echo "Remove $tmp_folder temp folder."
rm -rf "$tmp_folder"

# Remove the lock file when the script is done
echo "Remove $lockfile lock file."
rm -f "$lockfile"
