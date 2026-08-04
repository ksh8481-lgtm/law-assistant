document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('design-form');
    const submitBtn = document.getElementById('submit-btn');
    const btnText = document.getElementById('btn-text');
    const spinner = document.getElementById('spinner');
    const progressSection = document.getElementById('progress-section');

    // 파일 입력박스 연동
    const fileInputs = [
        { id: 'file-report', nameId: 'name-report', boxId: 'box-report' },
        { id: 'file-estimate', nameId: 'name-estimate', boxId: 'box-estimate' },
        { id: 'file-drawing', nameId: 'name-drawing', boxId: 'box-drawing' }
    ];

    fileInputs.forEach(item => {
        const input = document.getElementById(item.id);
        const nameDisplay = document.getElementById(item.nameId);
        const box = document.getElementById(item.boxId);

        if (input) {
            input.addEventListener('change', (e) => {
                if (e.target.files.length > 0) {
                    if (e.target.files.length === 1) {
                        const file = e.target.files[0];
                        nameDisplay.textContent = `✔ ${file.name} (${(file.size / 1024 / 1024).toFixed(2)} MB)`;
                    } else {
                        let totalSize = 0;
                        for(let i=0; i<e.target.files.length; i++) {
                            totalSize += e.target.files[i].size;
                        }
                        nameDisplay.textContent = `✔ ${e.target.files.length}개 파일 선택됨 (${(totalSize / 1024 / 1024).toFixed(2)} MB)`;
                    }
                    box.classList.add('has-file');
                } else {
                    nameDisplay.textContent = '';
                    box.classList.remove('has-file');
                }
            });
        }
    });

    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const projectName = document.getElementById('project-name').value.trim();
            const projectDomain = document.getElementById('project-domain').value;
            const additionalNotes = document.getElementById('additional-notes').value.trim();

            // 체크박스 모드 수집
            const checkedModes = Array.from(document.querySelectorAll('input[name="review-mode"]:checked'))
                                     .map(cb => cb.value);

            // 파일 묶음 가져오기
            const reportFiles = document.getElementById('file-report').files;
            const estimateFiles = document.getElementById('file-estimate').files;
            const drawingFiles = document.getElementById('file-drawing').files;

            if (reportFiles.length === 0 && estimateFiles.length === 0 && drawingFiles.length === 0 && !additionalNotes) {
                alert('💡 설계보고서, 내역서, 도면 중 하나 이상을 첨부하거나 추가 질의를 입력해주세요!');
                return;
            }

            const formData = new FormData();
            formData.append('projectName', projectName);
            formData.append('projectDomain', projectDomain);
            formData.append('reviewModes', JSON.stringify(checkedModes));
            formData.append('additionalNotes', additionalNotes);

            for (let i = 0; i < reportFiles.length; i++) {
                formData.append('file_report', reportFiles[i]);
            }
            for (let i = 0; i < estimateFiles.length; i++) {
                formData.append('file_estimate', estimateFiles[i]);
            }
            for (let i = 0; i < drawingFiles.length; i++) {
                formData.append('file_drawing', drawingFiles[i]);
            }

            // UI 변경 (로딩 상태)
            submitBtn.disabled = true;
            btnText.textContent = 'KCSC MCP 및 듀얼 엔진 분석 진행 중...';
            spinner.classList.remove('hidden');
            progressSection.classList.remove('hidden');

            // 스텝 애니메이션 초기화
            document.getElementById('step-1').className = 'progress-step active';
            document.getElementById('step-2').className = 'progress-step';
            document.getElementById('step-3').className = 'progress-step';

            try {
                // 1. 작업 요청
                const response = await fetch('/api/analyze/design_review', {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    const errorText = await response.text();
                    let errMsg = `서버 오류 발생 (상태 코드: ${response.status})`;
                    if (response.status === 413) {
                        errMsg = '파일 용량이 서버 제한을 초과했습니다 (413 Payload Too Large). Cloudtype 등의 서버 설정에서 최대 업로드 용량을 늘려주세요.';
                    } else {
                        try {
                            const errJson = JSON.parse(errorText);
                            if (errJson.message) errMsg = errJson.message;
                        } catch(e) {
                            errMsg += `\n내용: ${errorText.substring(0, 50)}...`;
                        }
                    }
                    throw new Error(errMsg);
                }

                const data = await response.json();
                const jobId = data.jobId;

                // 2. 상태 폴링 (Polling)
                let pollCount = 0;
                while (true) {
                    await new Promise(resolve => setTimeout(resolve, 2000));
                    pollCount++;

                    if (pollCount == 3) {
                        document.getElementById('step-1').className = 'progress-step';
                        document.getElementById('step-2').className = 'progress-step active';
                    } else if (pollCount == 6) {
                        document.getElementById('step-2').className = 'progress-step';
                        document.getElementById('step-3').className = 'progress-step active';
                    }

                    const statusRes = await fetch(`/api/analyze/status/${jobId}`);
                    if (!statusRes.ok) {
                        const errText = await statusRes.text();
                        throw new Error(`상태 확인 중 오류 발생 (상태 코드: ${statusRes.status})`);
                    }

                    const statusText = await statusRes.text();
                    let statusData;
                    try {
                        statusData = JSON.parse(statusText);
                    } catch(e) {
                        throw new Error(`서버 응답 파싱 실패: ${statusText.substring(0, 50)}...`);
                    }

                    if (statusData.status === 'completed') {
                        // 세션 스토리지에 결과 저장 후 보고서 탭 열기
                        sessionStorage.setItem('aiResult', JSON.stringify(statusData.result));
                        sessionStorage.setItem('projectData', JSON.stringify({
                            projectName: projectName,
                            projectDomain: projectDomain,
                            reviewType: 'design_review',
                            reviewModes: checkedModes
                        }));
                        
                        window.open('/report', '_blank');
                        break;
                    } else if (statusData.status === 'error') {
                        throw new Error(statusData.message || '검토 과정에서 오류가 발생했습니다.');
                    }
                }

            } catch (error) {
                console.error(error);
                alert('🚨 분석 실패: ' + error.message);
            } finally {
                submitBtn.disabled = false;
                btnText.textContent = '🚀 AI 기반 설계도서 정밀 교차검증 시작 (KCSC MCP 연동)';
                spinner.classList.add('hidden');
                progressSection.classList.add('hidden');
            }
        });
    }
});
