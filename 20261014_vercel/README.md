# 20261014_vercel — Vercel 배포용 정적 사이트

의사록 자동작성 PoC의 **정적 데모**를 Vercel(`*.vercel.app`)에 바로 올릴 수 있도록 재구성한 폴더입니다.
모든 데이터는 **교육용 가상(더미)**이며 실제 회사·인물과 무관합니다.

> 참고: 실제 Streamlit 앱(`../20261014/app.py`)은 지속 실행 서버가 필요해 Vercel에 맞지 않습니다.
> 이 폴더는 동일 UX를 재현한 정적 데모이며, 실제 앱은 사내 폐쇄망/Streamlit Cloud에서 구동합니다.

## 구성

| 파일 | URL | 내용 |
| --- | --- | --- |
| `index.html` | `/` | 데모 허브 (아래 3개로 이동) |
| `app.html` | `/app` | 의사록 자동작성 웹앱 (5탭 인터랙티브 데모) |
| `sample.html` | `/sample` | 의사록 양식 더미 샘플 문서 |
| `architecture.html` | `/architecture` | 시스템 아키텍처·설계 개요 |
| `vercel.json` | — | 정적 설정 (cleanUrls 등) |

`cleanUrls: true` 라서 `.html` 없이 `/app`, `/sample`, `/architecture` 로 접근됩니다.

## 배포 방법 (Vercel 대시보드)

1. [vercel.com](https://vercel.com) → **Continue with GitHub** 로그인
2. **Add New… → Project**
3. **Import** 에서 `moyah21-ship-it/261007` 선택 (안 보이면 GitHub App 권한에서 이 저장소 허용)
4. **Configure Project**:
   - **Root Directory**: `20261014_vercel`
   - **Framework Preset**: `Other`
   - Build Command / Output Directory: 비워둠 (정적)
5. **Deploy** → `https://<프로젝트명>.vercel.app` 생성

이후 이 브랜치에 push하면 자동 재배포됩니다. Production Branch는 Project Settings → Git 에서 지정합니다.

## 로컬 미리보기

```bash
cd 20261014_vercel
python3 -m http.server 8000   # http://localhost:8000
```
