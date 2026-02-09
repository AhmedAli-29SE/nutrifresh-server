// DOM Elements
const uploadArea = document.getElementById('upload-area');
const fileInput = document.getElementById('file-input');
const previewSection = document.getElementById('preview-section');
const previewImage = document.getElementById('preview-image');
const removeImageBtn = document.getElementById('remove-image');
const analyzeUploadBtn = document.getElementById('analyze-upload');

const webcam = document.getElementById('webcam');
const canvas = document.getElementById('canvas');
const capturedImage = document.getElementById('captured-image');
const startWebcamBtn = document.getElementById('start-webcam');
const captureBtn = document.getElementById('capture-btn');
const retakeBtn = document.getElementById('retake-btn');
const analyzeWebcamBtn = document.getElementById('analyze-webcam');

const resultsSection = document.getElementById('results-section');
const loadingDiv = document.getElementById('loading');
const errorMessage = document.getElementById('error-message');
const errorText = document.getElementById('error-text');

const modeBtns = document.querySelectorAll('.mode-btn');
const uploadMode = document.getElementById('upload-mode');
const webcamMode = document.getElementById('webcam-mode');

let webcamStream = null;

// Mode Switching
modeBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        const mode = btn.dataset.mode;
        
        // Update active button
        modeBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        
        // Show/hide content
        if (mode === 'upload') {
            uploadMode.classList.add('active');
            webcamMode.classList.remove('active');
            stopWebcam();
        } else {
            webcamMode.classList.add('active');
            uploadMode.classList.remove('active');
        }
        
        // Hide results and errors
        resultsSection.style.display = 'none';
        errorMessage.style.display = 'none';
    });
});

// Upload Mode - Click to upload
uploadArea.addEventListener('click', () => {
    fileInput.click();
});

// Drag and drop
uploadArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadArea.classList.add('dragover');
});

uploadArea.addEventListener('dragleave', () => {
    uploadArea.classList.remove('dragover');
});

uploadArea.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadArea.classList.remove('dragover');
    
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith('image/')) {
        handleImageFile(file);
    }
});

// File input change
fileInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) {
        handleImageFile(file);
    }
});

// Handle image file
function handleImageFile(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
        previewImage.src = e.target.result;
        uploadArea.style.display = 'none';
        previewSection.style.display = 'block';
        resultsSection.style.display = 'none';
        errorMessage.style.display = 'none';
    };
    reader.readAsDataURL(file);
}

// Remove image
removeImageBtn.addEventListener('click', () => {
    fileInput.value = '';
    previewImage.src = '';
    uploadArea.style.display = 'block';
    previewSection.style.display = 'none';
    resultsSection.style.display = 'none';
});

// Analyze uploaded image
analyzeUploadBtn.addEventListener('click', async () => {
    const file = fileInput.files[0];
    if (!file) return;
    
    const formData = new FormData();
    formData.append('file', file);
    
    await analyzeImage('/predict', formData, false);
});

// Webcam - Start
startWebcamBtn.addEventListener('click', async () => {
    try {
        webcamStream = await navigator.mediaDevices.getUserMedia({ 
            video: { facingMode: 'environment' } 
        });
        webcam.srcObject = webcamStream;
        webcam.style.display = 'block';
        capturedImage.style.display = 'none';
        
        startWebcamBtn.style.display = 'none';
        captureBtn.style.display = 'inline-flex';
        
        resultsSection.style.display = 'none';
        errorMessage.style.display = 'none';
    } catch (error) {
        showError('Unable to access webcam. Please check permissions.');
    }
});

// Webcam - Capture
captureBtn.addEventListener('click', () => {
    canvas.width = webcam.videoWidth;
    canvas.height = webcam.videoHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(webcam, 0, 0);
    
    const imageData = canvas.toDataURL('image/jpeg');
    capturedImage.src = imageData;
    
    webcam.style.display = 'none';
    capturedImage.style.display = 'block';
    
    captureBtn.style.display = 'none';
    retakeBtn.style.display = 'inline-flex';
    analyzeWebcamBtn.style.display = 'inline-flex';
    
    stopWebcam();
});

// Webcam - Retake
retakeBtn.addEventListener('click', async () => {
    try {
        webcamStream = await navigator.mediaDevices.getUserMedia({ 
            video: { facingMode: 'environment' } 
        });
        webcam.srcObject = webcamStream;
        webcam.style.display = 'block';
        capturedImage.style.display = 'none';
        
        retakeBtn.style.display = 'none';
        analyzeWebcamBtn.style.display = 'none';
        captureBtn.style.display = 'inline-flex';
        
        resultsSection.style.display = 'none';
    } catch (error) {
        showError('Unable to access webcam. Please check permissions.');
    }
});

// Stop webcam
function stopWebcam() {
    if (webcamStream) {
        webcamStream.getTracks().forEach(track => track.stop());
        webcamStream = null;
    }
}

// Analyze webcam image
analyzeWebcamBtn.addEventListener('click', async () => {
    const imageData = capturedImage.src;
    await analyzeImage('/predict_webcam', { image: imageData }, true);
});

// Analyze image function
async function analyzeImage(endpoint, data, isWebcam) {
    try {
        showLoading();
        hideError();
        resultsSection.style.display = 'none';
        
        const options = {
            method: 'POST'
        };
        
        if (isWebcam) {
            options.headers = {
                'Content-Type': 'application/json'
            };
            options.body = JSON.stringify(data);
        } else {
            options.body = data;
        }
        
        const response = await fetch(endpoint, options);
        const result = await response.json();
        
        hideLoading();
        
        if (response.ok) {
            displayResults(result);
        } else {
            showError(result.error || 'An error occurred during analysis');
        }
    } catch (error) {
        hideLoading();
        showError('Network error. Please check your connection and try again.');
    }
}

// Display results
function displayResults(result) {
    // Set fruit name and confidence
    document.getElementById('fruit-name').textContent = result.fruit_name;
    document.getElementById('fruit-confidence').textContent = result.fruit_confidence + '%';
    document.getElementById('fruit-confidence-bar').style.width = result.fruit_confidence + '%';
    
    // Set freshness status and confidence
    document.getElementById('freshness-status').textContent = result.freshness_status;
    document.getElementById('freshness-emoji').textContent = result.freshness_emoji;
    document.getElementById('freshness-confidence').textContent = result.freshness_confidence + '%';
    document.getElementById('freshness-confidence-bar').style.width = result.freshness_confidence + '%';
    
    // Set freshness badge
    const badge = document.getElementById('freshness-badge');
    badge.textContent = result.freshness_status;
    badge.className = 'freshness-badge ' + result.status_type;
    
    // Set detailed info
    document.getElementById('prediction-value').textContent = result.prediction_value;
    document.getElementById('analysis-date').textContent = new Date().toLocaleString();
    
    // Display Top 5 Predictions
    displayTop5Predictions(result.top_5_predictions);
    
    // Set recommendation
    const recommendation = getRecommendation(result);
    document.getElementById('recommendation-text').textContent = recommendation;
    
    // Style recommendation box based on status
    const recBox = document.getElementById('recommendation-box');
    if (result.status_type === 'success') {
        recBox.style.background = 'linear-gradient(135deg, rgba(16, 185, 129, 0.1), rgba(99, 102, 241, 0.1))';
    } else if (result.status_type === 'warning') {
        recBox.style.background = 'linear-gradient(135deg, rgba(245, 158, 11, 0.1), rgba(249, 115, 22, 0.1))';
    } else {
        recBox.style.background = 'linear-gradient(135deg, rgba(239, 68, 68, 0.1), rgba(220, 38, 38, 0.1))';
    }
    
    resultsSection.style.display = 'block';
}

// Get recommendation based on status
function getRecommendation(result) {
    const fruitName = result.fruit_name;
    
    if (result.freshness_status === 'FRESH') {
        return `This ${fruitName} is fresh and perfect for immediate consumption! Enjoy it raw or use it in your favorite recipes. Store properly to maintain freshness.`;
    } else if (result.freshness_status === 'MEDIUM FRESH') {
        return `This ${fruitName} is moderately fresh. It's still safe to eat but should be consumed soon. Consider using it in cooked dishes, smoothies, or baking where appearance is less critical.`;
    } else {
        return `This ${fruitName} appears to be past its prime. It may not be safe for consumption. Consider composting it or disposing of it properly. Always check for mold or unusual odors before use.`;
    }
}

// Show loading with animated stages
function showLoading() {
    loadingDiv.style.display = 'block';
    
    // Animate loading stages
    const stages = ['loading-text-1', 'loading-text-2', 'loading-text-3'];
    let currentStage = 0;
    
    const interval = setInterval(() => {
        // Remove active from all
        stages.forEach(id => {
            document.getElementById(id).classList.remove('active');
        });
        
        // Add active to current
        if (currentStage < stages.length) {
            document.getElementById(stages[currentStage]).classList.add('active');
            currentStage++;
        } else {
            clearInterval(interval);
        }
    }, 800);
}

function hideLoading() {
    loadingDiv.style.display = 'none';
}

function showError(message) {
    errorText.textContent = message;
    errorMessage.style.display = 'flex';
}

function hideError() {
    errorMessage.style.display = 'none';
}

// Analyze another button
document.getElementById('analyze-another').addEventListener('click', () => {
    resultsSection.style.display = 'none';
    
    // Reset upload mode
    fileInput.value = '';
    previewImage.src = '';
    uploadArea.style.display = 'block';
    previewSection.style.display = 'none';
    
    // Reset webcam mode
    capturedImage.src = '';
    webcam.style.display = 'none';
    capturedImage.style.display = 'none';
    startWebcamBtn.style.display = 'inline-flex';
    captureBtn.style.display = 'none';
    retakeBtn.style.display = 'none';
    analyzeWebcamBtn.style.display = 'none';
});

// Display Top 5 Predictions
function displayTop5Predictions(predictions) {
    const predictionsContainer = document.getElementById('top-5-predictions');
    predictionsContainer.innerHTML = '';
    
    if (!predictions || predictions.length === 0) {
        predictionsContainer.innerHTML = '<p style="text-align: center; color: var(--text-light);">No predictions available</p>';
        return;
    }
    
    predictions.forEach((prediction, index) => {
        const item = document.createElement('div');
        item.className = 'prediction-item' + (index === 0 ? ' top' : '');
        
        item.innerHTML = `
            <span class="prediction-rank">${index + 1}</span>
            <span class="prediction-name">${prediction.name}</span>
            <span class="prediction-confidence">${prediction.confidence}%</span>
        `;
        
        predictionsContainer.appendChild(item);
    });
}

