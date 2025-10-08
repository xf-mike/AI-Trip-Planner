class UserModel:

    def __init__(self, mode="cli"):
        if mode == "cli":
            self = CLI()
        elif mode == "remote":
            raise ValueError("remote server unimplement!")

    def get_input(self) -> str:
        pass


    def send_update(self, message: str) -> None:
        pass
    

class CLI:
    
    def get_input(self) -> str:
        return input("[User] > ").strip().encode("utf-8", errors="replace").decode("utf-8")


    def send_response(self, message: str) -> None:
        print(f"[Agent] > {message.encode('utf-8', errors='replace').decode('utf-8')}")