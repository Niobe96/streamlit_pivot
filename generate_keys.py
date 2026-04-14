from streamlit_authenticator.utilities.hasher import Hasher

passwords = ["admin1!"]

# 리스트 단위 해시 생성
hashed_passwords = Hasher.hash_list(passwords)

for pw, hashed in zip(passwords, hashed_passwords):
    print(f"{pw}  ->  {hashed}")
