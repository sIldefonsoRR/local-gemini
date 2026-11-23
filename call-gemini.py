from google import genai
import time
from google.genai.types import HttpOptions

client = genai.Client(
    api_key="unused",
    http_options=HttpOptions(
        api_version="v1",
        base_url="http://localhost:4000"
    )
)

# Get the question from the user
question = input("Enter your question: ")

print("Calling Gemini API...")
start_time = time.time()
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=question,
    )
print(response.text)
end_time = time.time()
print(f"Time taken: {end_time - start_time} seconds")
