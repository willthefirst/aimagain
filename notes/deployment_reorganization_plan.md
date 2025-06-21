# 🏗️ deployment reorganization implementation plan

## 🎯 Overview

**Goal**: Organize deployment files and automate the SCP process so we never have to manually copy files to the droplet again.

**Current State**:

- Deployment files scattered in root directory
- Manual SCP of scripts to droplet required
- GitHub Actions just runs `./deploy.sh` on droplet

**Target State**:

- All deployment files organized in `deployment/` structure
- GitHub Actions automatically syncs deployment files via SCP
- Clean separation of build-time vs runtime files
- Comprehensive deployment documentation

## 📋 Implementation steps

**⚠️ IMPORTANT**: Complete each step and verify it works before proceeding to the next step. Check off boxes as you go.

### **Phase 1: Create New Directory Structure**

**Goal**: Set up organized file structure without breaking anything
**Risk**: None - no existing functionality changed
**Time**: 15 minutes

#### Step 1.1: Create Directory Structure

- [ ] Create `deployment/` directory
- [ ] Create `deployment/droplet-files/` directory
- [ ] Create `deployment/scripts/` directory (for future helper scripts)

**Test After This Step**: Verify directories exist and are empty

#### Step 1.2: Move Files to New Structure

- [ ] Move `deploy.sh` → `deployment/droplet-files/deploy.sh`
- [ ] Move `docker-compose.blue-green.yml` → `deployment/droplet-files/docker-compose.blue-green.yml`
- [ ] Move `cleanup-docker.sh` → `deployment/droplet-files/cleanup-docker.sh`

**Test After This Step**:

- [ ] Verify files exist in new locations
- [ ] Verify old files are gone from root
- [ ] **DO NOT TEST DEPLOYMENT YET** - GitHub Actions will fail until Phase 2

### **Phase 2: Update GitHub Actions to Use SCP**

**Goal**: Automate file sync so GitHub Actions copies files before running deployment
**Risk**: Medium - deployment will break if SCP fails
**Time**: 30 minutes

#### Step 2.1: Update GitHub Actions Workflow

- [ ] Open `.github/workflows/build-and-push.yml`
- [ ] Add SCP step before deployment
- [ ] Update the deploy step to use new file locations

**New workflow steps**:

```yaml
- name: Copy deployment files to droplet
  uses: appleboy/scp-action@v0.1.7
  with:
    host: ${{ secrets.DROPLET_HOST }}
    username: ${{ secrets.DROPLET_USERNAME }}
    key: ${{ secrets.DROPLET_SSH_KEY }}
    source: 'deployment/droplet-files/*'
    target: '/opt/aimagain/'
    strip_components: 2

- name: Run deployment
  uses: appleboy/ssh-action@v1.0.3
  with:
    host: ${{ secrets.DROPLET_HOST }}
    username: ${{ secrets.DROPLET_USERNAME }}
    key: ${{ secrets.DROPLET_SSH_KEY }}
    script: |
      cd /opt/aimagain
      chmod +x deploy.sh cleanup-docker.sh
      ./deploy.sh
```

**Test After This Step**:

- [ ] Make a small change (like update README)
- [ ] Push to main branch
- [ ] Watch GitHub Actions workflow
- [ ] Verify SCP step succeeds
- [ ] Verify deployment runs successfully
- [ ] Verify website still works

**Rollback Plan**: If this fails, manually SCP the old files back to droplet

### **Phase 3: Update File References**

**Goal**: Update any hardcoded file paths in deployment scripts
**Risk**: Low - just cleanup work
**Time**: 15 minutes

#### Step 3.1: Check for Hardcoded Paths

- [ ] Review `deployment/droplet-files/deploy.sh` for any relative path references
- [ ] Update any references to `docker-compose.blue-green.yml` to use correct path
- [ ] Review `cleanup-docker.sh` for any path issues

**Common updates needed**:

```bash
# Old (if found):
docker-compose -f ../docker-compose.blue-green.yml up -d

# New:
docker-compose -f docker-compose.blue-green.yml up -d
```

**Test After This Step**:

- [ ] Make another small change and push to main
- [ ] Verify deployment still works
- [ ] Test `cleanup-docker.sh` manually on droplet

### **Phase 4: Clean Up Root Directory**

**Goal**: Keep Docker build files in root, remove deployment clutter
**Risk**: None - just organization
**Time**: 10 minutes

#### Step 4.1: Verify Required Root Files

- [ ] Confirm `Dockerfile` stays in root (needed for build context)
- [ ] Confirm `.dockerignore` stays in root (needed for build context)
- [ ] Remove any temporary/backup files created during moves

**Test After This Step**:

- [ ] Docker build still works locally: `docker build -t test .`
- [ ] GitHub Actions build still works (check recent workflow)

### **Phase 5: create documentation**

**Goal**: Document the new deployment setup
**Risk**: None - just documentation
**Time**: 30 minutes

#### Step 5.1: Create Deployment README

- [ ] Create `deployment/README.md`
- [ ] Document the file structure
- [ ] Document how the SCP automation works
- [ ] Document manual deployment process (for emergencies)
- [ ] Document how to update deployment scripts

**Test After This Step**:

- [ ] Review documentation for accuracy
- [ ] Have someone else (or AI) review the docs

## 🔍 Final verification checklist

Once all phases complete, verify the entire system:

- [ ] **File Organization**: All deployment files in logical locations
- [ ] **Automated SCP**: GitHub Actions copies files automatically
- [ ] **Deployment Works**: Push to main triggers successful deployment
- [ ] **Manual Fallback**: Can still SSH to droplet and run deployment manually
- [ ] **Documentation**: Clear docs for future maintenance
- [ ] **Clean Root**: Only necessary files remain in project root

## 📚 File structure reference

**Final structure should look like**:

├── .github/workflows/
│ └── build-and-push.yml # Updated with SCP step
├── deployment/
│ ├── README.md # New: Deployment documentation
│ └── droplet-files/ # New: Files that go to /opt/aimagain/
│ ├── deploy.sh # Moved from root
│ ├── docker-compose.blue-green.yml # Moved from root
│ └── cleanup-docker.sh # Moved from root
├── Dockerfile # Stays in root (build context)
└── .dockerignore # Stays in root (build context)

## 🚨 Emergency rollback

If anything breaks during implementation:

1. **Stop and assess** - don't proceed to next phase
2. **Manual deployment**: SSH to droplet and run deployment manually
3. **File recovery**: Files are in git history, can be restored
4. **GitHub Actions**: Can temporarily disable workflow if needed

## 📋 Success criteria

Implementation is complete when:

- ✅ All deployment files organized in `deployment/` structure
- ✅ GitHub Actions automatically syncs files (no more manual SCP)
- ✅ Deployment still works reliably
- ✅ Documentation explains the setup clearly
- ✅ Root directory is clean and organized

---

**Remember**: Take it step by step. Verify each phase works before moving on. When in doubt, test the deployment to make sure the website still works!
