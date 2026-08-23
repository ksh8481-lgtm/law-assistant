document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('commencement-form');
    const submitBtn = document.getElementById('submit-btn');
    const btnText = document.getElementById('btn-text');
    const spinner = document.getElementById('spinner');
    const progressSection = document.getElementById('progress-section');

    const fileInput = document.getElementById('file-input');
    const fileNameDisplay = document.getElementById('file-name-display');
    const uploadBox = document.getElementById('upload-box');

    if (fileInput) {
        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                if (e.target.files.length === 1) {
                    const file = e.target.files[0];
                    fileNameDisplay.textContent = `✔ ${file.name} (${(file.size / 1024 / 1024).toFixed(2)} MB)`;
                } else {
                    let totalSize = 0;
                    for (let i = 0; i < e.target.files.length; i++) {
                        totalSize += e.target.files[i].size;
                    }
                    fileNameDisplay.textContent = `✔ ${e.target.files.length}개 파일 선택됨 (${(totalSize / 1024 / 1024).toFixed(2)} MB)`;
                }
                uploadBox.classList.add('has-file');
            } else {
                fileNameDisplay.textContent = '';
                uploadBox.classList.remove('has-file');
            }
        });
    }

    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const projectName = document.getElementById('project-name').value.trim();
            const contractAmount = document.getElementById('contract-amount').value.trim();
            const totalCost = document.getElementById('total-cost').value.trim();
            const additionalNotes = document.getElementById('additional-notes').value.trim();
            const files = fileInput.files;

            if (files.length === 0) {
                alert('💡 착공계 관련 서류를 하나 이상 첨부해주세요!');
                return;
            }

            const formData = new FormData();
            formData.append('projectName', projectName);
            formData.append('contractAmount', contractAmount);
            formData.append('totalCost', totalCost);
            formData.append('additionalNotes', additionalNotes);
            for (let i = 0; i < files.length; i++) {
                formData.append('files', files[i]);
            }

            submitBtn.disabled = true;
            btnText.textContent = '착공서류 검토 진행 중...';
            spinner.classList.remove('hidden');
            progressSection.classList.remove('hidden');

            document.getElementById('step-1').className = 'progress-step active';
            document.getElementById('step-2').className = 'progress-step';
            document.getElementById('step-3').className = 'progress-step';

            try {
                const response = await fetch('/api/analyze/commencement_review', {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    const errorText = await response.text();
                    let errMsg = `서버 오류 발생 (상태 코드: ${response.status})`;
                    if (response.status === 413) {
                        errMsg = '파일 용량이 서버 제한을 초과했습니다 (413 Payload Too Large).';
                    } else {
                        try {
                            const errJson = JSON.parse(errorText);
                            if (errJson.message) errMsg = errJson.message;
                        } catch (e) {
                            errMsg += `\n내용: ${errorText.substring(0, 50)}...`;
                        }
                    }
                    throw new Error(errMsg);
                }

                const data = await response.json();
                if (!data.success) {
                    throw new Error(data.message || '요청이 거부되었습니다.');
                }
                const jobId = data.jobId;

                // 2초 간격, 최대 5분(150회) 폴링 후 포기
                const MAX_POLL_ATTEMPTS = 150;
                let pollCount = 0;
                while (true) {
                    await new Promise(resolve => setTimeout(resolve, 2000));
                    pollCount++;

                    if (pollCount > MAX_POLL_ATTEMPTS) {
                        throw new Error("응답 시간이 너무 오래 걸립니다 (5분 초과). 서버가 지연 중일 수 있으니 잠시 후 다시 시도해주세요.");
                    }

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
                    } catch (e) {
                        throw new Error(`서버 응답 파싱 실패: ${statusText.substring(0, 50)}...`);
                    }

                    if (statusData.status === 'completed') {
                        sessionStorage.setItem('aiResult', JSON.stringify(statusData.result));
                        sessionStorage.setItem('projectData', JSON.stringify({
                            projectName: projectName,
                            reviewType: 'commencement_review'
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
                btnText.textContent = '🚧 착공서류 AI 검토 시작';
                spinner.classList.add('hidden');
                progressSection.classList.add('hidden');
            }
        });
    }
});
