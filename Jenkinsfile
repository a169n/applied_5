// Main CI/CD pipeline. Each stage calls the Makefile target with the same name, so any stage
// can be reproduced locally. Stages 9 and 10 run only on main, and only on a SUCCESS build:
// an UNSTABLE build (for example, no real-data snapshot) never ships.
pipeline {
    agent any

    options {
        skipDefaultCheckout(true)
        timestamps()
        buildDiscarder(logRotator(numToKeepStr: '20'))
        disableConcurrentBuilds()
    }

    environment {
        IMAGE = "${env.DOCKERHUB_USER}/quakeloc"
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                script {
                    env.GIT_SHA = sh(script: 'git rev-parse HEAD', returnStdout: true).trim()
                    env.SHORT_SHA = sh(script: 'git rev-parse --short HEAD', returnStdout: true).trim()
                    def branch = env.BRANCH_NAME.toLowerCase().replaceAll('[^a-z0-9_.-]', '-')
                    env.TAG = "${env.SHORT_SHA}-${branch}-${env.BUILD_NUMBER}"
                }
            }
        }
        stage('Build test image') {
            steps {
                sh 'make image-test'
            }
        }
        stage('Lint') {
            steps {
                sh 'make lint'
            }
        }
        stage('Unit & property tests') {
            steps {
                sh 'make test'
            }
        }
        stage('Scientific validation') {
            steps {
                sh 'make calibrate science'
            }
        }
        stage('Real-data validation') {
            steps {
                script {
                    if (fileExists('data/real/MANIFEST.json')) {
                        sh 'make realdata'
                    } else {
                        unstable('real-data snapshot missing')
                    }
                }
            }
        }
        stage('Build runtime image') {
            steps {
                sh 'make image'
            }
        }
        stage('Container smoke test') {
            steps {
                sh 'make smoke'
            }
        }
        stage('Push to Docker Hub') {
            when {
                allOf {
                    branch 'main'
                    expression { currentBuild.currentResult == 'SUCCESS' }
                }
            }
            steps {
                withCredentials([usernamePassword(credentialsId: 'dockerhub',
                                                  usernameVariable: 'DOCKERHUB_LOGIN',
                                                  passwordVariable: 'DOCKERHUB_TOKEN')]) {
                    sh '''
                        echo "$DOCKERHUB_TOKEN" | docker login -u "$DOCKERHUB_LOGIN" --password-stdin
                        docker push "$IMAGE:$SHORT_SHA"
                        docker tag "$IMAGE:$SHORT_SHA" "$IMAGE:latest"
                        docker push "$IMAGE:latest"
                        docker logout
                    '''
                }
            }
        }
        stage('Deploy to Minikube') {
            when {
                allOf {
                    branch 'main'
                    expression { currentBuild.currentResult == 'SUCCESS' }
                    expression { sh(script: 'test -s /kube/config', returnStatus: true) == 0 }
                }
            }
            steps {
                sh 'k8s/deploy.sh "$IMAGE:$SHORT_SHA"'
            }
        }
    }

    post {
        always {
            junit allowEmptyResults: true, testResults: 'reports/*.xml'
            recordCoverage(tools: [[parser: 'COBERTURA', pattern: 'reports/coverage.xml']],
                           sourceCodeRetention: 'NEVER')
            archiveArtifacts allowEmptyArchive: true, fingerprint: true,
                             artifacts: 'artifacts/*, reports/*.csv'
            sh 'make clean-build'
            cleanWs()
        }
    }
}
