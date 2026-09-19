"""이 PC가 같은 네트워크에서 쓰는 사설 IP 하나를 찾아 출력한다."""
import socket


def find_lan_ip() -> str:
    # 실제로 패킷을 보내지 않고, 라우팅 테이블상 외부로 나갈 때 쓰는
    # 인터페이스의 로컬 주소를 알아내는 표준 기법.
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except OSError:
        ip = ""
    finally:
        s.close()

    # 사설망 대역인지 확인
    if ip.startswith(("192.168.", "10.")) or ip.startswith(
        tuple(f"172.{i}." for i in range(16, 32))
    ):
        return ip
    return ip  # 그래도 뭔가 잡히면 그대로


if __name__ == "__main__":
    print(find_lan_ip())
