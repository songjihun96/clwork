import sys; sys.path.insert(0,".")
from app import privacy
OK=[]
def chk(n,c,e=""):
    OK.append(bool(c)); print(("  OK  " if c else "  FAIL")+f"  {n}"+(f"  {e}" if not c and e else ""))

class U:
    name="홍길동"; school_name="근명고등학교"; email="hong@example.com"
    class_name="2학년 3반"; department="기계과"

print("=== 1. 아는 것을 가린다 ===")
p=privacy.build(U())
t="저는 근명고등학교 기계과 홍길동입니다. hong@example.com 으로 연락 주세요."
m=p.mask(t)
for word in ("홍길동","근명고등학교","hong@example.com","기계과"):
    chk(f"{word} 가려짐", word not in m, m)
chk("자리표로 바뀜", "[[" in m, m)
chk("되돌리면 원래대로", p.unmask(m)==t, p.unmask(m))

print("=== 2. 모르는 것도 생김새로 ===")
p=privacy.build(U())
t=("김철수 선생님께서 도와주셨습니다. 제 번호는 010-1234-5678 이고 "
   "친구 메일은 chulsoo@naver.com 입니다. 주민번호는 010203-3456789 입니다.")
m=p.mask(t)
chk("전화번호", "010-1234-5678" not in m, m)
chk("남의 이메일", "chulsoo@naver.com" not in m, m)
chk("주민번호", "010203-3456789" not in m, m)
chk("남의 이름", "김철수" not in m, m)
chk("호칭은 남음", "선생님" in m, m)
chk("되돌리기", p.unmask(m)==t)

print("=== 3. 새는지 확인 ===")
chk("가린 뒤엔 안 샘", privacy.find_leaks(m)==[], str(privacy.find_leaks(m)))
chk("안 가리면 잡힘", set(privacy.find_leaks(t))=={"주민등록번호","이메일","전화번호"},
    str(privacy.find_leaks(t)))

print("=== 4. 글이 망가지지 않는다 ===")
p=privacy.build(U())
t="선반 실습에서 치수가 0.2mm 커서 세 번 다시 했습니다. 이송 속도를 줄이니 맞았습니다."
m=p.mask(t)
chk("멀쩡한 글은 그대로", m==t, m)
chk("치수는 안 가려짐", "0.2mm" in m)

print("=== 5. 같은 말은 같은 자리표 ===")
p=privacy.build(U())
m=p.mask("홍길동은 근명고등학교 학생입니다. 홍길동은 성실합니다.")
import re as _re
toks=_re.findall(r"\[\[PERSON_\d+\]\]", m)
chk("두 번 나와도 같은 자리표", len(set(toks))==1 and len(toks)==2, str(toks))

print("=== 6. 긴 말 먼저 ===")
p=privacy.build(U())
m=p.mask("근명고등학교에 다닙니다.")
chk("학교명이 통째로", "근명" not in m and "고등학교" not in m, m)

print("=== 7. AI 가 자리표를 지워도 안 터진다 ===")
p=privacy.build(U())
p.mask("홍길동입니다.")
chk("모르는 자리표는 그대로", p.unmask("[[PERSON_9]] 님") == "[[PERSON_9]] 님")
chk("빈 글", p.unmask("")=="" and p.mask("")=="")

print("=== 8. 짧은 이름은 등록하지 않는다 ===")
class Short: name="김"; school_name=""; email=""; class_name=""; department=""
p=privacy.build(Short())
m=p.mask("김치를 먹었습니다.")
chk("한 글자는 안 가림", m=="김치를 먹었습니다.", m)
print("=== 9. 평범한 말을 가리지 않는다 ===")
# 실제로 겪은 일: '맡겠다고' 가 '맡겠다'+'고' 로 잘려 학교 이름으로 잡혔다.
# 초안에 [[SCHOOL_2]] 가 열 개 넘게 박혀 나왔다.
p=privacy.build(U())
plain = [
 "김민수가 자료 조사 맡겠다고 했는데",
 "발표는 그럭저럭 끝났고 선생님이 잘했다고 하셨다",
 "오늘 선생님이 말씀하셨다",
 "국어 선생님께 여쭤봤다",
 "강의실은 넓었다",
 "안전모가 필요하다",
 "이번에는 잘했다",
 "선반작업이 어려웠다",
 "조별과제가 힘들었다",
 "밤 11시부터 새벽 3시까지 했다",
]
for t in plain:
    m = privacy.build(U()).mask(t)
    chk(f"{t[:16]}", m == t, m)

print("=== 10. 진짜 개인정보는 여전히 가린다 ===")
for t, kind in [("김민수 선생님께서 도와주셨다","PERSON"),
                ("근명고등학교에 다닌다","SCHOOL"),
                ("010-1234-5678 로 연락","PHONE"),
                ("hong@naver.com 입니다","EMAIL")]:
    m = privacy.build(U()).mask(t)
    chk(f"{kind} 가림", f"[[{kind}" in m, m)

print(); print(f"===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
