import requests
import warnings

# This is needed to ignore the self-signed certificate warning
from requests.packages.urllib3.exceptions import InsecureRequestWarning
warnings.simplefilter('ignore', InsecureRequestWarning)

# The base URL for the running gateway
BASE_URL = "https://localhost:5000/v1/api/"

# An endpoint to check authentication status
auth_status_endpoint = "iserver/auth/status"

def main() -> None:
    print("Attempting to connect to the Client Portal Gateway...")

    try:
        # Make the request to the gateway
        # verify=False is required to accept the self-signed certificate
        response = requests.post(BASE_URL + auth_status_endpoint, verify=False)

        # This will raise an error if the request was unsuccessful
        response.raise_for_status()

        data = response.json()
        print("\n✅ Successfully connected to the gateway!")

        if data.get('authenticated'):
            print("   - Authentication Status: Authenticated")
            print(f"   - Session expires at: {data.get('expire')}")
        else:
            print("   - Authentication Status: Not Authenticated")

    except requests.exceptions.RequestException as e:
        print("\n❌ Failed to connect to the gateway.")
        print("   Please ensure the gateway is running and you have logged in via your browser.")
        print(f"   Error: {e}")


if __name__ == "__main__":
    main()
