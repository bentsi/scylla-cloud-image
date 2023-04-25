Name:           %{package_name}
Version:        %{version}
Release:        %{release}
Summary:        Scylla Machine Image
Group:          Applications/Databases

License:        ASL 2.0
URL:            http://www.scylladb.com/
Source0:        %{name}-%{version}-%{release}.tar
Requires:       %{product} = %{version} %{product}-python3 curl

BuildArch:      noarch
Obsoletes:      %{product}-ami

%global _python_bytecompile_errors_terminate_build 0
%global __brp_python_bytecompile %{nil}
%global __brp_mangle_shebangs %{nil}

%description


%prep
%setup -q


%build

%install
rm -rf $RPM_BUILD_ROOT

install -d m755 $RPM_BUILD_ROOT%{_unitdir}
install -m644 common/scylla-image-setup.service common/scylla-image-post-start.service common/scylla-cloud-snitch.service $RPM_BUILD_ROOT%{_unitdir}/
install -d -m755 $RPM_BUILD_ROOT/opt/scylladb
install -d -m755 $RPM_BUILD_ROOT/opt/scylladb/scylla-machine-image
install -d -m755 $RPM_BUILD_ROOT/opt/scylladb/scylla-machine-image/lib
install -m644 lib/log.py lib/scylla_cloud.py lib/user_data.py $RPM_BUILD_ROOT/opt/scylladb/scylla-machine-image/lib
install -m755 common/scylla_configure.py common/scylla_post_start.py common/scylla_create_devices \
        $RPM_BUILD_ROOT/opt/scylladb/scylla-machine-image/
./tools/relocate_python_scripts.py \
    --installroot $RPM_BUILD_ROOT/opt/scylladb/scylla-machine-image/ \
    --with-python3 ${RPM_BUILD_ROOT}/opt/scylladb/python3/bin/python3 \
    common/scylla_image_setup common/scylla_login common/scylla_configure.py \
    common/scylla_create_devices common/scylla_post_start.py \
    common/scylla_cloud_io_setup common/scylla_ec2_check \
    common/scylla_cloud_snitch

%pre
/usr/sbin/groupadd scylla 2> /dev/null || :
/usr/sbin/useradd -g scylla -s /sbin/nologin -r -d ${_sharedstatedir}/scylla scylla 2> /dev/null || :

%post
%systemd_post scylla-image-setup.service
%systemd_post scylla-image-post-start.service

%preun
%systemd_preun scylla-image-setup.service
%systemd_preun scylla-image-post-start.service

%postun
%systemd_postun scylla-image-setup.service
%systemd_postun scylla-image-post-start.service

%posttrans
if [ -L /home/scyllaadm/.bash_profile ] && [ ! -e /home/scyllaadm/.bash_profile ]; then
    rm /home/scyllaadm/.bash_profile
    cp /etc/skel/.bash_profile /home/scyllaadm/
    chown scyllaadm:scyllaadm /home/scyllaadm/.bash_profile
    echo -e '\n' >> /home/scyllaadm/.bash_profile
    echo "/opt/scylladb/scylla-machine-image/scylla_login" >> /home/scyllaadm/.bash_profile
fi

%clean
rm -rf $RPM_BUILD_ROOT


%files
%license LICENSE
%defattr(-,root,root)

%{_unitdir}/scylla-image-setup.service
%{_unitdir}/scylla-image-post-start.service
%{_unitdir}/scylla-cloud-snitch.service
/opt/scylladb/scylla-machine-image/*

%changelog
* Sun Nov 1 2020 Bentsi Magidovich <bentsi@scylladb.com>
- generalize scylla_create_devices
* Sun Jun 28 2020 Bentsi Magidovich <bentsi@scylladb.com>
- generalize code and support GCE image
* Wed Nov 20 2019 Bentsi Magidovich <bentsi@scylladb.com>
- Rename package to scylla-machine-image
* Mon Aug 20 2018 Takuya ASADA <syuu@scylladb.com>
- inital version of scylla-ami.spec

