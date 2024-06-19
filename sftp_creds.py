sftp_current_creds = {}

# Function to retrieve credentials based on session_id
def get_credentials(session_id):
    try:
        return sftp_current_creds[session_id]
    except KeyError:
        return None  # Return None or handle the error as per your application's logic

# Function to retrieve credentials based on session_id
def set_credentials(session_id, credential, value):
    try:
        return sftp_current_creds[session_id]
    except KeyError:
        return None  # Return None or handle the error as per your application's logic

def del_credentials(session_id):
    try:
        del sftp_current_creds[session_id]
    except KeyError:
        return None 
    
def create_random_integer():
    """
    Generates a really random positive integer using os.urandom.
    Ensures that the number is not interpreted as negative. Keeps track of generated numbers to ensure uniqueness.
    """
    # Initialize the set of generated numbers as a function attribute if it doesn't exist
    if not hasattr(create_random_integer, 'generated_numbers'):
        create_random_integer.generated_numbers = set()

    while True:
        # Generating a random byte string of length 4
        random_bytes = os.urandom(4)

        # Converting to a positive integer and masking the most significant bit
        random_integer = int.from_bytes(random_bytes, 'big') & 0x7FFFFFFF

        # Check if the number is unique
        if random_integer not in create_random_integer.generated_numbers:
            create_random_integer.generated_numbers.add(random_integer)
            return random_integer
